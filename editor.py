"""Interactive, fully-local Magic Eye studio — a step-by-step wizard.

A Tkinter UI (Python's built-in toolkit — no extra dependency, reliable mouse
events) that walks the whole conversion in the window, with nothing required on
the command line:

    1. Source      load a photo to cut out, or load a depth map directly
    2. Cutout      paint keep / cut / erase; zoom & pan; undo-redo; Refine
    3. Depth       paint the depth directly; zoom & pan; live previews
    4. Background   random dots or an image (tiled / wallpaper); place the
                   subject on the background with move + scale
    5. Preview      render with the chosen background, tune, and save

Editing is non-destructive: Ctrl+Z / Ctrl+Y undo and redo. Canvases zoom
(mouse-wheel), pan (right-drag), and scale with the window. Every slider reads
0-100. Everything is local: GrabCut only, no network, no ML download.

Usage:
    python editor.py [photo] [--background IMG] [--depth-in DEPTH]
                     [--out stereogram.png] [--depth-out depth.png] [--width 900]
"""

from __future__ import annotations

import argparse
import tkinter as tk
from tkinter import ttk, filedialog

import cv2
import numpy as np
from PIL import Image, ImageTk

import creator
import depthmap

STEPS = ["Source", "Cutout", "Depth", "Background", "Preview & Save"]


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


class EditorApp:
    def __init__(self, root, out, depth_out, work_w, photo, bg_path, depth_in):
        self.root = root
        self.out = out
        self.depth_out = depth_out
        self.work_w = work_w

        # Sliders are 0-100 IntVars; getters map them to real ranges.
        self.tool = tk.StringVar(value="fg")
        self.shape = tk.StringVar(value="rounded")
        self.carrier_mode = tk.StringVar(value="random")
        self.carrier_style = tk.StringVar(value="tile")
        self.v_brush = tk.IntVar(value=22)
        self.v_strength = tk.IntVar(value=100)
        self.v_pop = tk.IntVar(value=33)
        self.v_sep = tk.IntVar(value=50)
        self.v_bright = tk.IntVar(value=50)
        self.v_tile = tk.IntVar(value=20)
        self.v_subsize = tk.IntVar(value=33)

        # Image / working state.
        self.rgb = self.bgr = self.gc_mask = self.depth = None
        self.depth_mode = "cutout"
        self.bg_path = bg_path
        self.w = self.h = 0
        self.req_disp = 560
        self.disp_w, self.disp_h, self.scale = 560, 360, 1.0
        self.overlay = None                 # work-res (h, w, 4) RGBA strokes
        self._last_xy = None
        self._painting = False

        # View (zoom/pan) shared by the editing canvases.
        self.zoom = 1.0
        self.vx = self.vy = 0

        # Layout (place subject on a differently-sized background).
        self.layout_on = False
        self.out_w = self.out_h = 0
        self.sub_x = self.sub_y = 0
        self._layout_disp = (0, 0)
        self._drag_sub = None

        self.step = 0
        self._imgrefs = {}
        self.history, self.hist_i = [], -1
        self._resize_job = None

        self._build_shell()
        self.root.bind_all("<Control-z>", lambda e: self._undo())
        self.root.bind_all("<Control-y>", lambda e: self._redo())
        self.root.bind_all("<Control-Z>", lambda e: self._redo())
        self.root.bind_all("<KP_Add>", lambda e: self._kp_zoom(1.4))
        self.root.bind_all("<KP_Subtract>", lambda e: self._kp_zoom(1 / 1.4))
        self.root.bind("<Configure>", self._on_configure)

        if photo:
            self._load_photo(photo)
        if depth_in:
            self._load_depth_file(depth_in)
        if self.loaded:
            self._snapshot()
        self._show_step(0)

    # ---- slider getters ---------------------------------------------------
    def mu(self): return 0.05 + self.v_pop.get() / 100 * 0.85
    def eye_sep(self): return int(round(60 + self.v_sep.get() / 100 * 120))
    def brush_px(self): return int(round(2 + self.v_brush.get() / 100 * 58))
    def strength(self): return max(0.02, self.v_strength.get() / 100)
    def bright_factor(self): return self.v_bright.get() / 50
    def tile_zoom(self): return 0.5 + self.v_tile.get() / 100 * 2.5
    def subsize(self): return 0.25 + self.v_subsize.get() / 100 * 2.25

    @property
    def loaded(self): return self.depth is not None

    # ====================================================================
    # loading / sizing
    # ====================================================================
    def _recompute_disp(self):
        self.disp_w = min(self.req_disp, self.w) if self.w else self.req_disp
        self.scale = self.disp_w / self.w if self.w else 1.0
        self.disp_h = int(self.h * self.scale) if self.h else int(self.disp_w * .6)

    def _fit_view(self):
        self.zoom, self.vx, self.vy = 1.0, 0, 0

    def _load_photo(self, path):
        rgb = depthmap.load_rgb(path)
        h0, w0 = rgb.shape[:2]
        s = self.work_w / w0 if w0 > self.work_w else 1.0
        self.rgb = cv2.resize(rgb, (int(w0 * s), int(h0 * s)))
        self.h, self.w = self.rgb.shape[:2]
        self.bgr = cv2.cvtColor(self.rgb, cv2.COLOR_RGB2BGR)
        self._recompute_disp(); self._fit_view()
        self.overlay = np.zeros((self.h, self.w, 4), np.uint8)
        seed = depthmap.grabcut_mask(self.rgb)
        self.gc_mask = np.where(seed > 127, cv2.GC_PR_FGD,
                                cv2.GC_PR_BGD).astype(np.uint8)
        self.depth_mode = "cutout"
        self.depth = self._depth_from_mask()
        self.out_w, self.out_h = self.w, self.h

    def _load_depth_file(self, path):
        gray = np.asarray(Image.open(path).convert("L"), np.float64) / 255.0
        if self.rgb is None:
            h0, w0 = gray.shape
            s = self.work_w / w0 if w0 > self.work_w else 1.0
            self.h, self.w = int(h0 * s), int(w0 * s)
            self._recompute_disp(); self._fit_view()
            self.gc_mask = None
            self.overlay = np.zeros((self.h, self.w, 4), np.uint8)
            self.out_w, self.out_h = self.w, self.h
        self.depth = cv2.resize(gray, (self.w, self.h))
        self.depth_mode = "external"

    # ====================================================================
    # depth / carrier
    # ====================================================================
    def _fg255(self):
        if self.gc_mask is None:
            return np.full((self.h, self.w), 255, np.uint8)
        fg = (self.gc_mask == cv2.GC_FGD) | (self.gc_mask == cv2.GC_PR_FGD)
        return fg.astype(np.uint8) * 255

    def _depth_from_mask(self):
        return depthmap.mask_to_depth(self._fg255(), self.shape.get())

    def _eff_depth(self):
        """Depth actually rendered — the subject placed on the output canvas."""
        if not self.layout_on:
            return self.depth
        cw, ch = self.out_w, self.out_h
        canvas = np.zeros((ch, cw), np.float64)
        sc = self.subsize()
        sw, sh = max(1, int(self.w * sc)), max(1, int(self.h * sc))
        sub = cv2.resize(self.depth, (sw, sh))
        x, y = int(self.sub_x), int(self.sub_y)
        x0, y0, x1, y1 = max(0, x), max(0, y), min(cw, x + sw), min(ch, y + sh)
        if x1 > x0 and y1 > y0:
            canvas[y0:y1, x0:x1] = sub[y0 - y:y1 - y, x0 - x:x1 - x]
        return canvas

    def _carrier(self, height):
        es = self.eye_sep()
        if self.carrier_mode.get() == "image" and self.bg_path:
            if self.carrier_style.get() == "tile":
                img = Image.open(self.bg_path).convert("RGB")
                z = self.tile_zoom()
                img = img.resize((max(1, int(img.width * z)),
                                  max(1, int(img.height * z))))
                t = np.asarray(img, np.uint8)
                th, tw = t.shape[:2]
                base = t[np.ix_(np.arange(height) % th, np.arange(es) % tw)]
            else:
                base = creator.make_carrier(height, es, self.bg_path, None)
        else:
            rng = np.random.default_rng()
            base = rng.integers(0, 256, (height, es, 3), np.uint8)
        return np.clip(base.astype(np.float64) * self.bright_factor(),
                       0, 255).astype(np.uint8)

    def _render(self):
        eff = self._eff_depth()
        return creator.render(eff, self.eye_sep(), self.mu(), None, None,
                              carrier=self._carrier(eff.shape[0]))

    def _sep_preview(self):
        sep = creator.depth_to_separation(self.depth, self.eye_sep(),
                                          self.mu()).astype(np.float64)
        lo, hi = sep.min(), sep.max()
        g = (sep - lo) / (hi - lo + 1e-9) * 255
        return np.repeat(g.astype(np.uint8)[..., None], 3, 2)

    def _depth_rgb(self):
        return np.repeat((self.depth * 255).astype(np.uint8)[..., None], 3, 2)

    # ====================================================================
    # work-resolution composites + zoom/pan view
    # ====================================================================
    def _photo_work(self):
        return self.rgb if self.rgb is not None else self._depth_rgb()

    def _cut_work(self):
        a = self.overlay[..., 3:4].astype(np.float64) / 255
        rgb = self.overlay[..., :3].astype(np.float64)
        return (self._photo_work() * (1 - a) + rgb * a).astype(np.uint8)

    def _depth_work(self):
        d = self._depth_rgb().astype(np.float64)
        a = self.overlay[..., 3:4].astype(np.float64) / 255 * 0.4
        return (d * (1 - a) + self.overlay[..., :3].astype(np.float64) * a
                ).astype(np.uint8)

    def _cut_depth_work(self):
        """Depth (grayscale) with the SAME Keep/Cut strokes drawn on top — the
        right panel of the Cutout step, so the tools show on both sides."""
        d = self._depth_rgb().astype(np.float64)
        a = self.overlay[..., 3:4].astype(np.float64) / 255
        return (d * (1 - a) + self.overlay[..., :3].astype(np.float64) * a
                ).astype(np.uint8)

    def _view(self, work_arr):
        """Crop the working image to the current zoom/pan and fit the canvas."""
        z = self.zoom
        vw, vh = max(1, int(self.w / z)), max(1, int(self.h / z))
        self.vx = _clamp(self.vx, 0, self.w - vw)
        self.vy = _clamp(self.vy, 0, self.h - vh)
        crop = work_arr[self.vy:self.vy + vh, self.vx:self.vx + vw]
        interp = cv2.INTER_NEAREST if z > 1 else cv2.INTER_AREA
        return cv2.resize(crop, (self.disp_w, self.disp_h), interpolation=interp)

    def _c2w(self, cx, cy):
        z = self.zoom
        return (int(self.vx + cx / self.disp_w * (self.w / z)),
                int(self.vy + cy / self.disp_h * (self.h / z)))

    # ====================================================================
    # undo / redo
    # ====================================================================
    def _snapshot(self):
        snap = (None if self.gc_mask is None else self.gc_mask.copy(),
                self.depth.copy(),
                None if self.overlay is None else self.overlay.copy())
        self.history = self.history[:self.hist_i + 1]
        self.history.append(snap)
        if len(self.history) > 30:
            self.history.pop(0)
        self.hist_i = len(self.history) - 1

    def _restore(self):
        gm, d, ov = self.history[self.hist_i]
        self.gc_mask = None if gm is None else gm.copy()
        self.depth = d.copy()
        self.overlay = None if ov is None else ov.copy()
        self._refresh_active()

    def _undo(self):
        if self.hist_i > 0:
            self.hist_i -= 1; self._restore()
            self.status.config(text=f"Undo ({self.hist_i + 1}/{len(self.history)})")

    def _redo(self):
        if self.hist_i < len(self.history) - 1:
            self.hist_i += 1; self._restore()
            self.status.config(text=f"Redo ({self.hist_i + 1}/{len(self.history)})")

    def _refresh_active(self):
        if self.step == 1 and self.gc_mask is not None:
            # Live cutout -> depth (only while actually painting the cutout, so a
            # mere zoom/pan never clobbers a hand-painted depth from step 3).
            if self._painting or self.depth_mode == "cutout":
                self.depth = self._depth_from_mask()
                self.depth_mode = "cutout"
            self._put(self.left, self._view(self._cut_work()), "cut_l")
            self._put(self.right, self._view(self._cut_depth_work()), "cut_r")
        elif self.step == 2:
            self._put(self.left, self._view(self._depth_work()), "dep_l")
            self._put(self.right, self._sep_preview(), "dep_r")
        if hasattr(self, "zoom_lbl") and self.zoom_lbl.winfo_exists():
            self.zoom_lbl.config(text=f"{int(self.zoom * 100)}%")

    # ====================================================================
    # shell + responsive resize
    # ====================================================================
    def _build_shell(self):
        self.root.title("Magic Eye Studio")
        self.root.minsize(820, 560)
        crumb = ttk.Frame(self.root, padding=(8, 6))
        crumb.grid(row=0, column=0, sticky="ew")
        self.crumb_btns = []
        for i, name in enumerate(STEPS):
            b = ttk.Button(crumb, text=f"{i + 1}. {name}", width=15,
                           command=lambda i=i: self._goto(i))
            b.grid(row=0, column=i, padx=2)
            self.crumb_btns.append(b)
        self.content = ttk.Frame(self.root, padding=10)
        self.content.grid(row=1, column=0, sticky="nsew")
        self.root.rowconfigure(1, weight=1)
        self.root.columnconfigure(0, weight=1)
        nav = ttk.Frame(self.root, padding=(8, 6))
        nav.grid(row=2, column=0, sticky="ew")
        self.back_btn = ttk.Button(nav, text="← Back",
                                   command=lambda: self._goto(self.step - 1))
        self.back_btn.grid(row=0, column=0)
        self.status = ttk.Label(nav, text="Load a photo or depth map to begin. "
                                          "Ctrl+Z undo · Ctrl+Y redo.")
        self.status.grid(row=0, column=1, padx=12)
        self.next_btn = ttk.Button(nav, text="Next →",
                                   command=lambda: self._goto(self.step + 1))
        self.next_btn.grid(row=0, column=2)
        nav.columnconfigure(1, weight=1)

    def _on_configure(self, e):
        if e.widget is not self.root:
            return
        if self._resize_job:
            self.root.after_cancel(self._resize_job)
        self._resize_job = self.root.after(160, self._apply_resize)

    def _apply_resize(self):
        if not self.loaded:
            return
        avail_w = self.root.winfo_width()
        avail_h = self.root.winfo_height()
        # Two side-by-side canvases on the editing steps; one elsewhere.
        per = 2 if self.step in (1, 2) else 1
        by_w = (avail_w - 60) // per
        by_h = int((avail_h - 300) * self.w / self.h) if self.h else by_w
        new = _clamp(min(by_w, by_h), 240, 1100)
        if abs(new - self.req_disp) > 16:
            self.req_disp = new
            self._recompute_disp()
            self._show_step(self.step)

    def _goto(self, i):
        if i < 0 or i >= len(STEPS):
            return
        if i > 0 and not self.loaded:
            self.status.config(text="Load a source on step 1 first.")
            return
        self._show_step(i)

    def _show_step(self, i):
        self.step = i
        for w in self.content.winfo_children():
            w.destroy()
        for j, b in enumerate(self.crumb_btns):
            b.state(["pressed"] if j == i else ["!pressed"])
        self.back_btn.state(["disabled"] if i == 0 else ["!disabled"])
        self.next_btn.state(["disabled"] if i == len(STEPS) - 1 else ["!disabled"])
        [self._p_source, self._p_cutout, self._p_depth, self._p_background,
         self._p_preview][i](self.content)

    # ---- small widgets ----------------------------------------------------
    def _slider(self, parent, r, c, name, var, cb=None):
        s = tk.Scale(parent, from_=0, to=100, orient="horizontal", label=name,
                     variable=var, length=150, showvalue=True,
                     command=(lambda _v: cb()) if cb else None)
        s.grid(row=r, column=c, sticky="w", padx=4)
        return s

    def _put(self, canvas, arr, ref):
        img = Image.fromarray(arr)
        if img.size != (self.disp_w, self.disp_h):
            img = img.resize((self.disp_w, self.disp_h))
        self._imgrefs[ref] = ImageTk.PhotoImage(img)
        canvas.delete("all")
        canvas.create_image(0, 0, anchor="nw", image=self._imgrefs[ref])

    def _brush_preview(self, canvas):
        canvas.delete("all")
        r = min(int(self.brush_px() * self.scale * self.zoom), 34)
        col = {"fg": "#00c800", "bg": "#dc0000", "erase": "#888"}[self.tool.get()]
        canvas.create_oval(38 - r, 38 - r, 38 + r, 38 + r, outline=col, width=2)
        canvas.create_text(38, 72, text=f"{self.brush_px()} px")

    def _zoom_bar(self, parent):
        bar = ttk.Frame(parent)
        ttk.Button(bar, text="–", width=3,
                   command=lambda: self._zoom_to(self.zoom / 1.4)).grid(row=0, column=0)
        ttk.Button(bar, text="+", width=3,
                   command=lambda: self._zoom_to(self.zoom * 1.4)).grid(row=0, column=1)
        ttk.Button(bar, text="Fit", width=4,
                   command=lambda: (self._fit_view(), self._refresh_active())
                   ).grid(row=0, column=2)
        self.zoom_lbl = ttk.Label(bar, text=f"{int(self.zoom * 100)}%", width=6)
        self.zoom_lbl.grid(row=0, column=3, padx=4)
        ttk.Label(bar, text="(wheel = zoom, right-drag = pan)").grid(row=0, column=4)
        return bar

    def _zoom_to(self, z, cx=None, cy=None):
        cx = self.disp_w / 2 if cx is None else cx
        cy = self.disp_h / 2 if cy is None else cy
        wx, wy = self._c2w(cx, cy)
        self.zoom = _clamp(z, 1.0, 12.0)
        vw, vh = self.w / self.zoom, self.h / self.zoom
        self.vx = int(wx - cx / self.disp_w * vw)
        self.vy = int(wy - cy / self.disp_h * vh)
        self._refresh_active()

    def _bind_view(self, canvas):
        canvas.bind("<MouseWheel>",
                    lambda e: self._zoom_to(self.zoom * (1.2 if e.delta > 0
                                            else 1 / 1.2), e.x, e.y))
        canvas.bind("<ButtonPress-3>", self._pan_start)
        canvas.bind("<B3-Motion>", self._pan_move)

    def _kp_zoom(self, f):
        if self.step in (1, 2) and self.loaded:
            self._zoom_to(self.zoom * f)

    def _bind_edit(self, canvas):
        """Paint + zoom/pan + a live brush ring on an editing canvas."""
        canvas.bind("<ButtonPress-1>", self._paint_start)
        canvas.bind("<B1-Motion>", self._paint_move)
        canvas.bind("<ButtonRelease-1>", self._paint_end)
        canvas.bind("<Motion>", self._on_hover)
        canvas.bind("<Leave>", lambda e: e.widget.delete("ring"))
        self._bind_view(canvas)

    def _draw_ring(self, widget, x, y):
        widget.delete("ring")
        r = max(2, int(self.brush_px() * self.scale * self.zoom))
        col = {"fg": "#00c800", "bg": "#dc0000", "erase": "#888888"}[
            self.tool.get()]
        widget.create_oval(x - r, y - r, x + r, y + r, outline=col, width=2,
                           tags="ring")

    def _on_hover(self, e):
        # The ring is a sizing guide; it hides while a stroke is in progress.
        if not self._painting:
            self._draw_ring(e.widget, e.x, e.y)

    def _pan_start(self, e):
        self._pan_xy = (e.x, e.y)

    def _pan_move(self, e):
        vw, vh = self.w / self.zoom, self.h / self.zoom
        self.vx = int(self.vx - (e.x - self._pan_xy[0]) / self.disp_w * vw)
        self.vy = int(self.vy - (e.y - self._pan_xy[1]) / self.disp_h * vh)
        self._pan_xy = (e.x, e.y)
        self._refresh_active()

    # ====================================================================
    # STEP 1 — Source
    # ====================================================================
    def _p_source(self, parent):
        ttk.Label(parent, text="Start from a photo (we cut the subject out) "
                  "or load a depth map you painted.",
                  font=("", 11)).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Button(parent, text="Load photo…",
                   command=self._pick_photo).grid(row=1, column=0, pady=8, sticky="w")
        ttk.Button(parent, text="Load depth map…",
                   command=self._pick_depth).grid(row=1, column=1, pady=8, sticky="w")
        prev = tk.Canvas(parent, width=self.disp_w, height=self.disp_h,
                         highlightthickness=1, highlightbackground="#999")
        prev.grid(row=2, column=0, columnspan=2, pady=6)
        if self.loaded:
            self._put(prev, cv2.resize(self._photo_work(),
                      (self.disp_w, self.disp_h)), "src")
            self.status.config(text="Source loaded. Click Next.")

    def _pick_photo(self):
        path = filedialog.askopenfilename(
            title="Load a photo", filetypes=[
                ("Images", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff"),
                ("All files", "*.*")])
        if path:
            self.status.config(text="Cutting out subject (GrabCut)…")
            self.root.update_idletasks()
            self._load_photo(path)
            self.history.clear(); self.hist_i = -1; self._snapshot()
            self._show_step(0)

    def _pick_depth(self):
        path = filedialog.askopenfilename(
            title="Load a painted depth map (white = near, black = far)",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff"),
                       ("All files", "*.*")])
        if path:
            self._load_depth_file(path)
            self.history.clear(); self.hist_i = -1; self._snapshot()
            self._show_step(0)

    # ====================================================================
    # STEP 2 — Cutout
    # ====================================================================
    def _p_cutout(self, parent):
        if self.gc_mask is None:
            ttk.Label(parent, text="You loaded a depth map directly, so there's "
                      "no photo to cut out.\nUse step 3 to shape it, or go back "
                      "and load a photo.", font=("", 11)).grid(row=0, column=0)
            return
        bar = ttk.Frame(parent)
        bar.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        for col, (txt, val) in enumerate([("Keep", "fg"), ("Cut", "bg"),
                                          ("Eraser", "erase")]):
            ttk.Radiobutton(bar, text=txt, value=val, variable=self.tool,
                            command=lambda: self._brush_preview(self.bprev)
                            ).grid(row=0, column=col)
        ttk.Button(bar, text="Refine", command=self._refine).grid(row=0, column=3, padx=6)
        ttk.Button(bar, text="↶", width=3, command=self._undo).grid(row=0, column=4)
        ttk.Button(bar, text="↷", width=3, command=self._redo).grid(row=0, column=5)
        self._zoom_bar(bar).grid(row=0, column=6, padx=8)

        sl = ttk.Frame(parent)
        sl.grid(row=1, column=0, columnspan=2, sticky="w")
        self._slider(sl, 0, 0, "Brush", self.v_brush,
                     cb=lambda: self._brush_preview(self.bprev))
        self._slider(sl, 0, 1, "Eraser strength", self.v_strength)
        self.bprev = tk.Canvas(sl, width=76, height=84, highlightthickness=1,
                               highlightbackground="#999")
        self.bprev.grid(row=0, column=2, padx=8)
        self._brush_preview(self.bprev)

        self.left = tk.Canvas(parent, width=self.disp_w, height=self.disp_h,
                              cursor="crosshair", highlightthickness=1,
                              highlightbackground="#999")
        self.left.grid(row=2, column=0, padx=4)
        self.right = tk.Canvas(parent, width=self.disp_w, height=self.disp_h,
                               cursor="crosshair", highlightthickness=1,
                               highlightbackground="#999")
        self.right.grid(row=2, column=1, padx=4)
        # Both panels paint, zoom, pan, and show the ring — the tools and view
        # act on both sides at once.
        self._bind_edit(self.left)
        self._bind_edit(self.right)
        self._put(self.left, self._view(self._cut_work()), "cut_l")
        self._put(self.right, self._view(self._cut_depth_work()), "cut_r")
        self.status.config(text="Paint Keep/Cut/Erase (either panel), then "
                                "Refine. Wheel/Numpad +/- zoom, right-drag pan.")

    # ====================================================================
    # STEP 3 — Depth
    # ====================================================================
    def _p_depth(self, parent):
        bar = ttk.Frame(parent)
        bar.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        ttk.Label(bar, text="Paint:").grid(row=0, column=0)
        for col, (txt, val) in enumerate([("Nearer", "fg"), ("Farther", "bg"),
                                          ("Smooth", "erase")]):
            ttk.Radiobutton(bar, text=txt, value=val, variable=self.tool,
                            command=lambda: self._brush_preview(self.bprev2)
                            ).grid(row=0, column=col + 1)
        ttk.Radiobutton(bar, text="Rounded", value="rounded", variable=self.shape,
                        command=self._reshape).grid(row=0, column=4, padx=(10, 0))
        ttk.Radiobutton(bar, text="Flat", value="flat", variable=self.shape,
                        command=self._reshape).grid(row=0, column=5)
        self._zoom_bar(bar).grid(row=0, column=6, padx=8)

        bar2 = ttk.Frame(parent)
        bar2.grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 4))
        ttk.Button(bar2, text="Load depth…", command=self._pick_depth_here).grid(row=0, column=0)
        ttk.Button(bar2, text="Use cutout", command=self._use_cutout).grid(row=0, column=1, padx=2)
        ttk.Button(bar2, text="Clip to cutout", command=self._clip_to_cutout).grid(row=0, column=2, padx=2)
        ttk.Button(bar2, text="↶", width=3, command=self._undo).grid(row=0, column=3)
        ttk.Button(bar2, text="↷", width=3, command=self._redo).grid(row=0, column=4)

        sl = ttk.Frame(parent)
        sl.grid(row=2, column=0, columnspan=2, sticky="w")
        self._slider(sl, 0, 0, "Brush", self.v_brush,
                     cb=lambda: self._brush_preview(self.bprev2))
        self._slider(sl, 0, 1, "Strength", self.v_strength)
        self._slider(sl, 0, 2, "Depth pop", self.v_pop, cb=self._sep_refresh)
        self._slider(sl, 0, 3, "Separation", self.v_sep, cb=self._sep_refresh)
        self.bprev2 = tk.Canvas(sl, width=76, height=84, highlightthickness=1,
                                highlightbackground="#999")
        self.bprev2.grid(row=0, column=4, padx=8)
        self._brush_preview(self.bprev2)

        ttk.Label(parent, text="Depth (paintable)").grid(row=3, column=0)
        ttk.Label(parent, text="Separation preview").grid(row=3, column=1)
        self.left = tk.Canvas(parent, width=self.disp_w, height=self.disp_h,
                              cursor="crosshair", highlightthickness=1,
                              highlightbackground="#999")
        self.left.grid(row=4, column=0, padx=4)
        self.right = tk.Canvas(parent, width=self.disp_w, height=self.disp_h,
                               highlightthickness=1, highlightbackground="#999")
        self.right.grid(row=4, column=1, padx=4)
        self._bind_edit(self.left)
        self._put(self.left, self._view(self._depth_work()), "dep_l")
        self._put(self.right, self._sep_preview(), "dep_r")
        self.status.config(text=f"Depth source: {self.depth_mode}. Paint to "
                                "sculpt; wheel=zoom, right-drag=pan.")

    def _sep_refresh(self):
        if self.step == 2:
            self._put(self.right, self._sep_preview(), "dep_r")

    def _reshape(self):
        if self.depth_mode == "cutout":
            self.depth = self._depth_from_mask()
        self._snapshot(); self._refresh_active()

    def _pick_depth_here(self):
        path = filedialog.askopenfilename(
            title="Load a painted depth map (white = near, black = far)",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff"),
                       ("All files", "*.*")])
        if path:
            self._load_depth_file(path); self._snapshot(); self._refresh_active()

    def _use_cutout(self):
        if self.gc_mask is None:
            self.status.config(text="No photo cutout available."); return
        self.depth_mode = "cutout"; self.depth = self._depth_from_mask()
        self._snapshot(); self._refresh_active()

    def _clip_to_cutout(self):
        self.depth = self.depth * (self._fg255() / 255.0)
        self._snapshot(); self._refresh_active()
        self.status.config(text="Clipped depth to the cutout silhouette.")

    # ====================================================================
    # painting (shared)
    # ====================================================================
    def _paint_start(self, e):
        self._painting = True
        e.widget.delete("ring")                 # hide guide while painting
        self._last_xy = (e.x, e.y); self._stamp(e.x, e.y); self._refresh_active()

    def _paint_move(self, e):
        if self._last_xy is not None:
            x0, y0 = self._last_xy
            n = max(1, int(max(abs(e.x - x0), abs(e.y - y0)) / 3))
            for i in range(1, n + 1):
                self._stamp(x0 + (e.x - x0) * i // n, y0 + (e.y - y0) * i // n)
        self._last_xy = (e.x, e.y); self._refresh_active()

    def _paint_end(self, e):
        self._painting = False
        self._last_xy = None; self._snapshot()
        self._draw_ring(e.widget, e.x, e.y)     # bring the guide back

    def _stamp(self, cx, cy):
        mx, my = self._c2w(cx, cy)
        r = self.brush_px()
        tool = self.tool.get()
        if self.step == 1:
            if tool == "erase":
                cv2.circle(self.gc_mask, (mx, my), r, cv2.GC_PR_BGD, -1)
                m = np.zeros((self.h, self.w), np.float32)
                cv2.circle(m, (mx, my), r, 1.0, -1)
                self.overlay[..., 3] = (self.overlay[..., 3] *
                                        (1 - self.strength() * m)).astype(np.uint8)
            else:
                label = cv2.GC_FGD if tool == "fg" else cv2.GC_BGD
                cv2.circle(self.gc_mask, (mx, my), r, label, -1)
                col = (0, 200, 0, 150) if tool == "fg" else (220, 0, 0, 150)
                cv2.circle(self.overlay, (mx, my), r, col, -1)
        else:
            disk = np.zeros((self.h, self.w), np.float32)
            cv2.circle(disk, (mx, my), r, 1.0, -1)
            s = self.strength() * disk
            if tool == "fg":
                self.depth = self.depth * (1 - s) + 1.0 * s
            elif tool == "bg":
                self.depth = self.depth * (1 - s) + 0.0 * s
            else:
                blur = cv2.GaussianBlur(self.depth, (0, 0), r / 2 + 1)
                self.depth = self.depth * (1 - s) + blur * s
            self.depth_mode = "painted"

    def _refine(self):
        self.status.config(text="Refining (GrabCut)…"); self.root.update_idletasks()
        bgd = np.zeros((1, 65), np.float64); fgd = np.zeros((1, 65), np.float64)
        try:
            cv2.grabCut(self.bgr, self.gc_mask, None, bgd, fgd, 3,
                        cv2.GC_INIT_WITH_MASK)
        except cv2.error as exc:
            self.status.config(text=f"GrabCut skipped: {exc}"); return
        self.overlay = np.zeros((self.h, self.w, 4), np.uint8)
        self.depth_mode = "cutout"; self.depth = self._depth_from_mask()
        self._snapshot(); self._refresh_active()
        self.status.config(text="Refined. Paint more & Refine, or go Next.")

    # ====================================================================
    # STEP 4 — Background + layout
    # ====================================================================
    def _p_background(self, parent):
        ttk.Label(parent, text="Carrier — the visible surface of the Magic Eye.",
                  font=("", 11)).grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Radiobutton(parent, text="Random dots", value="random",
                        variable=self.carrier_mode, command=self._carrier_changed
                        ).grid(row=1, column=0, sticky="w")
        ttk.Radiobutton(parent, text="Image", value="image",
                        variable=self.carrier_mode, command=self._carrier_changed
                        ).grid(row=1, column=1, sticky="w")
        ttk.Button(parent, text="Load background…",
                   command=self._pick_bg).grid(row=1, column=2, sticky="w")
        self.bg_lbl = ttk.Label(parent, text=self.bg_path or "(none)")
        self.bg_lbl.grid(row=1, column=3, sticky="w")

        ttk.Radiobutton(parent, text="Tiled (full detail)", value="tile",
                        variable=self.carrier_style, command=self._carrier_changed
                        ).grid(row=2, column=1, sticky="w")
        ttk.Radiobutton(parent, text="Wallpaper (whole image)", value="wallpaper",
                        variable=self.carrier_style, command=self._carrier_changed
                        ).grid(row=2, column=2, sticky="w")

        lay = ttk.Frame(parent)
        lay.grid(row=3, column=0, columnspan=4, sticky="w", pady=(4, 0))
        self.layout_var = tk.BooleanVar(value=self.layout_on)
        ttk.Checkbutton(lay, text="Place subject on background (move + scale)",
                        variable=self.layout_var,
                        command=self._toggle_layout).grid(row=0, column=0)
        ttk.Button(lay, text="Match background size",
                   command=self._match_bg).grid(row=0, column=1, padx=6)
        ttk.Button(lay, text="Center", command=self._center_sub).grid(row=0, column=2)

        sl = ttk.Frame(parent)
        sl.grid(row=4, column=0, columnspan=4, sticky="w")
        self._slider(sl, 0, 0, "Tile size", self.v_tile, cb=self._carrier_changed)
        self._slider(sl, 0, 1, "Brightness", self.v_bright, cb=self._carrier_changed)
        self._slider(sl, 0, 2, "Subject size", self.v_subsize, cb=self._layout_refresh)

        self.swatch = tk.Canvas(parent, highlightthickness=1,
                                highlightbackground="#999")
        self.swatch.grid(row=5, column=0, columnspan=4, pady=8)
        self.swatch.bind("<ButtonPress-1>", self._sub_drag_start)
        self.swatch.bind("<B1-Motion>", self._sub_drag_move)
        self._carrier_changed()
        self.status.config(text="Pick a carrier. Toggle 'Place subject' to move "
                                "and scale the cutout on the background.")

    def _toggle_layout(self):
        self.layout_on = self.layout_var.get()
        if self.layout_on and (self.out_w, self.out_h) == (self.w, self.h):
            self._center_sub()
        self._layout_refresh()

    def _match_bg(self):
        if not self.bg_path:
            self.status.config(text="Load a background image first."); return
        bw, bh = Image.open(self.bg_path).size
        self.out_w = self.w
        self.out_h = max(1, int(round(self.w * bh / bw)))
        self.layout_on = True
        if hasattr(self, "layout_var"):
            self.layout_var.set(True)
        self._center_sub()

    def _center_sub(self):
        sc = self.subsize()
        self.sub_x = int((self.out_w - self.w * sc) / 2)
        self.sub_y = int((self.out_h - self.h * sc) / 2)
        self._layout_refresh()

    def _layout_refresh(self, *_):
        if self.step == 3:
            self._carrier_changed()

    def _pick_bg(self):
        path = filedialog.askopenfilename(
            title="Load a background/carrier image",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff"),
                       ("All files", "*.*")])
        if path:
            self.bg_path = path; self.carrier_mode.set("image")
            self.bg_lbl.config(text=path); self._carrier_changed()

    def _carrier_changed(self, *_):
        cw = self.out_w if self.layout_on else self.w
        ch = self.out_h if self.layout_on else self.h
        strip = self._carrier(ch)
        reps = max(1, cw // strip.shape[1] + 1)
        band = np.tile(strip, (1, reps, 1))[:, :cw].copy()
        if self.layout_on:
            sil = self._eff_depth() > 0.02
            band[sil] = (0.5 * band[sil] + np.array([0, 220, 0]) * 0.5
                         ).astype(np.uint8)
        dw = min(self.req_disp, 720)
        dh = max(1, int(dw * ch / cw))
        self._layout_disp = (dw, dh, cw, ch)
        self.swatch.config(width=dw, height=dh)
        self._imgrefs["swatch"] = ImageTk.PhotoImage(
            Image.fromarray(cv2.resize(band, (dw, dh))))
        self.swatch.delete("all")
        self.swatch.create_image(0, 0, anchor="nw", image=self._imgrefs["swatch"])

    def _sub_drag_start(self, e):
        self._drag_sub = (e.x, e.y, self.sub_x, self.sub_y)

    def _sub_drag_move(self, e):
        if not self.layout_on or self._drag_sub is None:
            return
        dw, dh, cw, ch = self._layout_disp
        ox, oy, sx, sy = self._drag_sub
        self.sub_x = int(sx + (e.x - ox) / dw * cw)
        self.sub_y = int(sy + (e.y - oy) / dh * ch)
        self._carrier_changed()

    # ====================================================================
    # STEP 5 — Preview & Save
    # ====================================================================
    def _p_preview(self, parent):
        bar = ttk.Frame(parent)
        bar.grid(row=0, column=0, sticky="w", pady=(0, 6))
        ttk.Button(bar, text="Render preview", command=self._do_preview).grid(row=0, column=0)
        ttk.Button(bar, text="Save…", command=self._save_as).grid(row=0, column=1, padx=12)
        sl = ttk.Frame(parent)
        sl.grid(row=1, column=0, sticky="w")
        self._slider(sl, 0, 0, "Depth pop", self.v_pop)
        self._slider(sl, 0, 1, "Separation", self.v_sep)
        self._slider(sl, 0, 2, "Brightness", self.v_bright)
        self.pcanvas = tk.Canvas(parent, width=self.disp_w, height=self.disp_h,
                                 highlightthickness=1, highlightbackground="#999")
        self.pcanvas.grid(row=2, column=0, pady=4)
        self.status.config(text="Render preview uses your chosen carrier & layout.")

    def _do_preview(self):
        self.status.config(text="Rendering…"); self.root.update_idletasks()
        self._preview_img = self._render()
        self._put(self.pcanvas, self._preview_img, "preview")
        self.status.config(text="Preview ready. Adjust and re-render, or Save.")

    def _save_as(self):
        stereo = getattr(self, "_preview_img", None)
        if stereo is None:
            stereo = self._render()
        path = filedialog.asksaveasfilename(
            title="Save Magic Eye", defaultextension=".png",
            initialfile=self.out, filetypes=[("PNG", "*.png")])
        if not path:
            return
        Image.fromarray(stereo).save(path)
        Image.fromarray((self._eff_depth() * 255).astype(np.uint8)).save(self.depth_out)
        self.status.config(text=f"Saved {path}  (+ depth {self.depth_out})")
        print(f"Saved stereogram to {path}")
        print(f"Saved depth map to {self.depth_out}")


def main():
    p = argparse.ArgumentParser(description="Interactive Magic Eye studio.")
    p.add_argument("photo", nargs="?", default=None,
                   help="Optional photo to start from (else load it in the UI)")
    p.add_argument("--background", default=None, help="Preset carrier image")
    p.add_argument("--depth-in", default=None, help="Preset painted depth map")
    p.add_argument("--out", default="stereogram.png", help="Default save name")
    p.add_argument("--depth-out", default="depth.png", help="Depth map output")
    p.add_argument("--width", type=int, default=900, help="Working width")
    args = p.parse_args()

    root = tk.Tk()
    EditorApp(root, args.out, args.depth_out, args.width, args.photo,
              args.background, args.depth_in)
    root.mainloop()


if __name__ == "__main__":
    main()
