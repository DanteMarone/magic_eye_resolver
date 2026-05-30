"""Interactive, fully-local cutout + carrier editor for the Magic Eye creator.

A Tkinter UI (Python's built-in toolkit — no extra dependency, reliable mouse
events) to FIX the automatic cutout by painting, and CHOOSE the carrier, then
render the autostereogram. Everything runs locally; GrabCut only, no downloads.

Why Tkinter: the previous OpenCV-HighGUI window didn't deliver mouse events on
some Windows builds, so painting silently did nothing. Tkinter's Canvas gives
dependable mouse input and lets us put real clickable tool buttons on screen.

Layout
  Left canvas   the photo; drag to paint. Green = keep (foreground),
                red = cut (background).
  Right canvas  the live depth map derived from the current cutout.
  Toolbar       Keep / Cut tools, Refine (re-run GrabCut from strokes),
                Shape (rounded/flat), Carrier (random/image), brush + brightness
                sliders, Preview, Save.

Usage:
    python editor.py <photo> [--background IMG] [--out stereogram.png]
                     [--depth-out depth.png] [--width 900]
                     [--eye-sep N] [--mu F] [--display N]
"""

from __future__ import annotations

import argparse
import tkinter as tk
from tkinter import ttk, filedialog

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageTk

import creator
import depthmap


class EditorApp:
    def __init__(self, root: tk.Tk, photo: str, bg_path: str | None,
                 work_w: int, disp_w: int, eye_sep: int, mu: float,
                 out: str, depth_out: str, depth_in: str | None = None) -> None:
        self.root = root
        self.eye_sep = eye_sep
        self.mu = mu
        self.out = out
        self.depth_out = depth_out

        # Working-resolution photo (fast to edit/render).
        rgb = depthmap.load_rgb(photo)
        h0, w0 = rgb.shape[:2]
        s = work_w / w0 if w0 > work_w else 1.0
        self.rgb = cv2.resize(rgb, (int(w0 * s), int(h0 * s)))
        self.h, self.w = self.rgb.shape[:2]
        self.bgr = cv2.cvtColor(self.rgb, cv2.COLOR_RGB2BGR)

        # Display scale: shrink the on-screen canvas to fit comfortably.
        self.disp_w = min(disp_w, self.w)
        self.scale = self.disp_w / self.w          # display px per work px
        self.disp_h = int(self.h * self.scale)

        # GrabCut label mask (0=bg,1=fg,2=pr_bg,3=pr_fg), seeded from a rect.
        seed = depthmap.grabcut_mask(self.rgb)     # 0/255
        self.gc_mask = np.where(seed > 127, cv2.GC_PR_FGD,
                                cv2.GC_PR_BGD).astype(np.uint8)

        # Editing state, driven by the toolbar.
        self.tool = "fg"          # "fg" = keep, "bg" = cut
        self.shape = "rounded"
        self.carrier_mode = "random"
        self.brush = tk.IntVar(value=14)
        self.bright = tk.IntVar(value=100)
        self.bg_path = bg_path

        self.photo_disp = Image.fromarray(self.rgb).resize(
            (self.disp_w, self.disp_h))
        self.overlay = Image.new("RGBA", (self.disp_w, self.disp_h), (0, 0, 0, 0))
        # Depth comes either from the cutout ("cutout") or an externally painted
        # grayscale image ("external", white = near, black = far).
        self.depth_mode = "cutout"
        self.depth = self._depth_from_mask()
        self._last_xy: tuple[int, int] | None = None

        self._build_ui()
        if depth_in is not None:
            self._set_external_depth(depth_in)
        self._refresh_left()
        self._refresh_right()

    # --- depth / carrier ---------------------------------------------------
    def _fg255(self) -> np.ndarray:
        fg = (self.gc_mask == cv2.GC_FGD) | (self.gc_mask == cv2.GC_PR_FGD)
        return fg.astype(np.uint8) * 255

    def _depth_from_mask(self) -> np.ndarray:
        return depthmap.mask_to_depth(self._fg255(), self.shape)

    def _carrier(self) -> np.ndarray:
        if self.carrier_mode == "image" and self.bg_path is not None:
            base = creator.make_carrier(self.h, self.eye_sep, self.bg_path, None)
        else:
            rng = np.random.default_rng()
            base = rng.integers(0, 256, (self.h, self.eye_sep, 3), np.uint8)
        scaled = base.astype(np.float64) * (self.bright.get() / 100.0)
        return np.clip(scaled, 0, 255).astype(np.uint8)

    # --- UI construction ---------------------------------------------------
    def _build_ui(self) -> None:
        self.root.title("Magic Eye Editor")
        bar = ttk.Frame(self.root, padding=6)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew")

        self.tool_lbl = ttk.Label(bar, text="Tool: KEEP", width=12)
        ttk.Button(bar, text="Keep (green)",
                   command=lambda: self._set_tool("fg")).grid(row=0, column=0)
        ttk.Button(bar, text="Cut (red)",
                   command=lambda: self._set_tool("bg")).grid(row=0, column=1)
        self.tool_lbl.grid(row=0, column=2, padx=8)
        ttk.Button(bar, text="Refine cutout",
                   command=self._refine).grid(row=0, column=3, padx=4)
        self.shape_btn = ttk.Button(bar, text="Shape: rounded",
                                    command=self._toggle_shape)
        self.shape_btn.grid(row=0, column=4, padx=4)
        self.carrier_btn = ttk.Button(bar, text="Carrier: random",
                                      command=self._toggle_carrier)
        self.carrier_btn.grid(row=0, column=5, padx=4)
        ttk.Button(bar, text="Load depth…",
                   command=self._load_depth).grid(row=0, column=6, padx=4)
        ttk.Button(bar, text="Use cutout",
                   command=self._use_cutout).grid(row=0, column=7, padx=4)
        ttk.Button(bar, text="Clip to cutout",
                   command=self._clip_to_cutout).grid(row=0, column=8, padx=4)
        ttk.Button(bar, text="Preview",
                   command=self._preview).grid(row=0, column=9, padx=4)
        ttk.Button(bar, text="Save + Quit",
                   command=self._save).grid(row=0, column=10, padx=4)

        sliders = ttk.Frame(self.root, padding=(6, 0))
        sliders.grid(row=1, column=0, columnspan=2, sticky="ew")
        ttk.Label(sliders, text="Brush").grid(row=0, column=0)
        ttk.Scale(sliders, from_=2, to=60, variable=self.brush,
                  length=160).grid(row=0, column=1, padx=(2, 16))
        ttk.Label(sliders, text="Carrier brightness").grid(row=0, column=2)
        ttk.Scale(sliders, from_=20, to=200, variable=self.bright,
                  length=160).grid(row=0, column=3, padx=2)

        self.left = tk.Canvas(self.root, width=self.disp_w, height=self.disp_h,
                              highlightthickness=0, cursor="crosshair")
        self.left.grid(row=2, column=0, padx=4, pady=4)
        self.right = tk.Canvas(self.root, width=self.disp_w, height=self.disp_h,
                               highlightthickness=0)
        self.right.grid(row=2, column=1, padx=4, pady=4)

        self.left.bind("<ButtonPress-1>", self._paint_start)
        self.left.bind("<B1-Motion>", self._paint_move)
        self.left.bind("<ButtonRelease-1>", self._paint_end)

        self.status = ttk.Label(self.root, padding=(6, 2),
                                text="Drag on the left image to paint. "
                                     "Keep=green, Cut=red, then Refine.")
        self.status.grid(row=3, column=0, columnspan=2, sticky="w")

    # --- painting ----------------------------------------------------------
    def _set_tool(self, tool: str) -> None:
        self.tool = tool
        self.tool_lbl.config(text=f"Tool: {'KEEP' if tool == 'fg' else 'CUT'}")

    def _paint_start(self, event) -> None:
        self._last_xy = (event.x, event.y)
        self._stamp(event.x, event.y)

    def _paint_move(self, event) -> None:
        # Interpolate between events so fast drags leave a continuous stroke.
        if self._last_xy is not None:
            x0, y0 = self._last_xy
            steps = max(1, int(max(abs(event.x - x0), abs(event.y - y0)) / 3))
            for i in range(1, steps + 1):
                self._stamp(x0 + (event.x - x0) * i // steps,
                            y0 + (event.y - y0) * i // steps)
        self._last_xy = (event.x, event.y)
        self._refresh_left()

    def _paint_end(self, _event) -> None:
        self._last_xy = None
        self._refresh_left()

    def _stamp(self, dx: int, dy: int) -> None:
        """Paint one brush dab at display coords (dx, dy)."""
        label = cv2.GC_FGD if self.tool == "fg" else cv2.GC_BGD
        r_mask = self.brush.get()
        # Stamp the GrabCut mask at working resolution.
        mx, my = int(dx / self.scale), int(dy / self.scale)
        cv2.circle(self.gc_mask, (mx, my), r_mask, label, -1)
        # Stamp the display overlay (so the user sees the stroke immediately).
        r_disp = max(1, int(r_mask * self.scale))
        color = (0, 200, 0, 130) if self.tool == "fg" else (220, 0, 0, 130)
        ImageDraw.Draw(self.overlay).ellipse(
            [dx - r_disp, dy - r_disp, dx + r_disp, dy + r_disp], fill=color)

    # --- actions -----------------------------------------------------------
    def _refine(self) -> None:
        self.status.config(text="Refining cutout (GrabCut)...")
        self.root.update_idletasks()
        bgd = np.zeros((1, 65), np.float64)
        fgd = np.zeros((1, 65), np.float64)
        try:
            cv2.grabCut(self.bgr, self.gc_mask, None, bgd, fgd, 3,
                        cv2.GC_INIT_WITH_MASK)
        except cv2.error as exc:
            self.status.config(text=f"GrabCut skipped: {exc}")
            return
        # Clear the stroke overlay; the cutout now reflects the strokes.
        self.overlay = Image.new("RGBA", (self.disp_w, self.disp_h),
                                 (0, 0, 0, 0))
        self.depth_mode = "cutout"
        self.depth = self._depth_from_mask()
        self._refresh_left()
        self._refresh_right()
        self.status.config(text="Refined. Paint more and Refine again, or Save.")

    def _toggle_shape(self) -> None:
        self.shape = "flat" if self.shape == "rounded" else "rounded"
        self.shape_btn.config(text=f"Shape: {self.shape}")
        if self.depth_mode == "cutout":
            self.depth = self._depth_from_mask()
            self._refresh_right()
        else:
            self.status.config(text="Shape applies to the cutout; depth is "
                                    "external. Use cutout to switch back.")

    def _set_external_depth(self, path: str) -> None:
        """Load a hand-painted grayscale depth map (white=near, black=far)."""
        gray = np.asarray(Image.open(path).convert("L"), dtype=np.float64) / 255.0
        self.depth = cv2.resize(gray, (self.w, self.h))
        self.depth_mode = "external"
        self._refresh_right()
        self.status.config(text=f"Loaded external depth: {path}")

    def _load_depth(self) -> None:
        path = filedialog.askopenfilename(
            title="Load a painted depth map (white = near, black = far)",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff"),
                       ("All files", "*.*")])
        if path:
            self._set_external_depth(path)

    def _use_cutout(self) -> None:
        self.depth_mode = "cutout"
        self.depth = self._depth_from_mask()
        self._refresh_right()
        self.status.config(text="Using cutout-derived depth.")

    def _clip_to_cutout(self) -> None:
        """Keep depth only inside the foreground cutout; flatten the rest."""
        self.depth = self.depth * (self._fg255() / 255.0)
        self._refresh_right()
        self.status.config(text="Clipped depth to the cutout silhouette.")

    def _toggle_carrier(self) -> None:
        if self.bg_path is None:
            self.status.config(text="No --background image given; staying random.")
            return
        self.carrier_mode = "image" if self.carrier_mode == "random" else "random"
        self.carrier_btn.config(text=f"Carrier: {self.carrier_mode}")

    def _preview(self) -> None:
        self.status.config(text="Rendering preview...")
        self.root.update_idletasks()
        stereo = creator.render(self.depth, self.eye_sep, self.mu,
                                None, None, carrier=self._carrier())
        win = tk.Toplevel(self.root)
        win.title("Magic Eye preview")
        img = Image.fromarray(stereo).resize((self.disp_w, self.disp_h))
        tkimg = ImageTk.PhotoImage(img)
        lbl = tk.Label(win, image=tkimg)
        lbl.image = tkimg            # keep a reference
        lbl.pack()
        self.status.config(text="Preview shown. Adjust and re-preview, or Save.")

    def _save(self) -> None:
        stereo = creator.render(self.depth, self.eye_sep, self.mu,
                                None, None, carrier=self._carrier())
        Image.fromarray(stereo).save(self.out)
        Image.fromarray((self.depth * 255).astype(np.uint8)).save(self.depth_out)
        print(f"Saved stereogram to {self.out}")
        print(f"Saved depth map to {self.depth_out}")
        self.root.destroy()

    # --- rendering the two canvases ---------------------------------------
    def _refresh_left(self) -> None:
        composite = Image.alpha_composite(
            self.photo_disp.convert("RGBA"), self.overlay).convert("RGB")
        self._left_img = ImageTk.PhotoImage(composite)
        self.left.create_image(0, 0, anchor="nw", image=self._left_img)

    def _refresh_right(self) -> None:
        depth_rgb = np.repeat((self.depth * 255).astype(np.uint8)[..., None],
                              3, axis=2)
        img = Image.fromarray(depth_rgb).resize((self.disp_w, self.disp_h))
        self._right_img = ImageTk.PhotoImage(img)
        self.right.create_image(0, 0, anchor="nw", image=self._right_img)


def main() -> None:
    p = argparse.ArgumentParser(description="Interactive Magic Eye editor.")
    p.add_argument("photo", help="Photo to cut out and turn into a Magic Eye")
    p.add_argument("--background", default=None,
                   help="Image to offer as the carrier (toggle in the UI)")
    p.add_argument("--out", default="stereogram.png", help="Stereogram output")
    p.add_argument("--depth-out", default="depth.png", help="Depth map output")
    p.add_argument("--depth-in", default=None,
                   help="Start from a hand-painted depth map (white=near, "
                        "black=far) instead of the cutout")
    p.add_argument("--width", type=int, default=900,
                   help="Working width; smaller = faster (default 900)")
    p.add_argument("--display", type=int, default=720,
                   help="On-screen canvas width per panel (default 720)")
    p.add_argument("--eye-sep", type=int, default=110, help="Carrier period px")
    p.add_argument("--mu", type=float, default=0.33, help="Depth strength 0..1")
    args = p.parse_args()

    root = tk.Tk()
    EditorApp(root, args.photo, args.background, args.width, args.display,
              args.eye_sep, args.mu, args.out, args.depth_out, args.depth_in)
    root.mainloop()


if __name__ == "__main__":
    main()
