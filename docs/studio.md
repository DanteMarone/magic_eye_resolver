# Studio — the interactive editor (`editor.py`)

`editor.py` ("Magic Eye Studio") is a **local**, step-by-step wizard built on
Tkinter (Python's built-in GUI — no extra dependency, no network, no ML
download). It does the whole conversion in one window: cut a subject out, sculpt
the depth, choose a carrier, place the subject, and render — or start from a
hand-painted depth map.

## Launch

```bash
python editor.py                                   # load everything in the UI
python editor.py photo.png                         # preset the photo
python editor.py photo.png --background art.png    # preset photo + carrier
python editor.py --depth-in my_depth.png           # start from a painted depth
```

| Flag | Meaning |
|------|---------|
| `photo` | Optional photo to start from (else load it in the UI) |
| `--background IMG` | Preset carrier image (toggle/styling in the UI) |
| `--depth-in DEPTH` | Start from a hand-painted depth map |
| `--out NAME` | Default save name (default `stereogram.png`) |
| `--depth-out NAME` | Depth map output name (default `depth.png`) |
| `--width N` | Working resolution width for responsive editing (default 900) |

## Global behaviour (every step)

- **Navigation** — **Back / Next** buttons, or click the numbered breadcrumb.
- **Undo / Redo** — **Ctrl+Z** / **Ctrl+Y** (also ↶/↷ buttons). Non-destructive;
  one history entry per brush stroke or action, ~30 deep. The stack stores the
  cutout mask, depth, and stroke overlay together, so undo works across cutout
  edits, depth edits, and Refine.
- **Sliders** — every slider reads **0–100** and shows its number.
- **Responsive** — all canvases scale with the window size.

## Step 1 — Source

- **Load photo…** — the subject is cut out automatically (GrabCut) and becomes the
  near plane.
- **Load depth map…** — skip the cutout and go straight to shaping a hand-painted
  depth (white = near, black = far). See [depth-maps.md](depth-maps.md).

## Step 2 — Cutout

Refine the automatic cut by painting. The two panels — **photo** (left) and live
**depth** (right) — share everything: tools, strokes, zoom and pan all act on
**both sides at once**.

- **Tools** — **Keep** (green, foreground), **Cut** (red, background), **Eraser**.
  Paint on either panel.
- **Eraser strength** — how strongly the eraser clears strokes (resets to
  "GrabCut decides").
- **Brush** slider — sets the brush radius; a preview box and a **cursor ring**
  (drawn over the image, scaled to the current zoom) show the size. The ring hides
  while you paint and returns on release.
- **Refine** — re-runs GrabCut using your strokes as hard constraints
  (`GC_INIT_WITH_MASK`). A few strokes go a long way.
- **Zoom / pan** — mouse-wheel (centred on cursor) or **Numpad +/−** to zoom;
  **right-drag** to pan; **+/−/Fit** buttons; live zoom %.

## Step 3 — Depth

Shape the depth map directly. Left panel = the **paintable depth**; right panel =
a **live grayscale separation preview** (what the encoder actually consumes).

- **Paint tools** — **Nearer** (raise/brighten), **Farther** (lower/darken),
  **Smooth** (blend toward a local blur to feather edges). Brush **size** +
  **strength**, with the same cursor ring and zoom/pan as Step 2.
- **Rounded / Flat** — relief shape when the depth is cutout-derived.
- **Load depth…** — import a hand-painted depth map.
- **Use cutout** — switch back to the cutout-derived depth.
- **Clip to cutout** — keep depth only inside the cutout silhouette, flatten the
  rest (`depth × mask`).
- **Depth pop** (→ µ) and **Separation** (→ eye-sep) sliders update the separation
  preview live.

## Step 4 — Background

Choose the carrier (the visible surface) and, optionally, place the subject on a
differently-sized background.

- **Random dots** / **Image** — carrier source.
- **Tiled (full detail)** vs **Wallpaper (whole image)** — for an image carrier;
  see [creator.md](creator.md#carriers). **Tile size** zooms the tiled art.
- **Brightness** — scales the carrier brightness.
- **Live swatch** — shows the repeating carrier exactly as the render will use it.
- **Place subject on background** (when subject and background differ in size):
  - **Match background size** — sets the output canvas to the art's aspect ratio.
  - **Drag** the subject in the swatch to reposition; **Subject size** to scale;
    **Center** to recentre.

Placement is a depth transform — the subject depth is pasted onto a far (zero)
canvas of the output size — so it flows through to both the render and the saved
depth map.

## Step 5 — Preview & Save

- **Render preview** — renders the full stereogram using **whatever carrier and
  layout you chose**.
- **Depth pop / Separation / Brightness** — fine-tune, then re-render.
- **Save…** — writes the stereogram (file picker) and the depth map
  (`--depth-out`).

## Working resolution vs. full resolution

The studio edits at `--width` (default 900 px) so painting and preview stay
responsive. The saved `depth.png` is at that width. For a print-quality final,
feed the saved depth back to the [creator](creator.md) at full size:

```bash
python creator.py depth.png --tile art.png --out final.png
```
