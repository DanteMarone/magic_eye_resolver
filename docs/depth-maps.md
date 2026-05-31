# Depth maps — photo cutout, shapes, and painting your own

A Magic Eye needs a **depth map**: a grayscale image where **white = nearest the
viewer** and **black = farthest**, with mid-greys for in-between. Both
[`creator.py`](creator.md) and the [studio](studio.md) accept one. There are
three ways to get a depth map.

## 1. Derive it from a photo (`depthmap.py`)

`depthmap.photo_to_depth()` cuts the foreground subject out of a photo (subject =
near, background = far). Used by `creator.py --from-photo` and by the studio.

### Cutout engines

- **`grabcut`** (default) — OpenCV GrabCut, auto-seeded by a centre rectangle.
  Self-contained, pinned, downloads nothing. Works best on a clear subject roughly
  centred in frame.
- **`rembg`** (opt-in) — U²-Net ML matting. Far better on arbitrary photos, but it
  is **not a declared dependency** because it downloads an ML model on first run.
  Install it yourself only if you accept that:
  ```bash
  pip install rembg
  ```
  If it is missing, the `rembg` path stops with instructions rather than silently
  fetching anything.

### Subject shape (`mask_to_depth`)

- **`rounded`** (default) — a distance transform domes the subject toward the
  viewer (interior nearest, falling off to the silhouette), for a relief-carving
  look. The falloff is `sqrt`-scaled so it's a dome, not a sharp cone.
- **`flat`** — subject on one near plane, background on one far plane: a clean
  two-level pop-out.

A light Gaussian blur removes stair-stepping that would otherwise band in the
result.

### Preview

`--from-photo` always writes a 3-panel `*_cutout_preview.png` — **original |
cut-out subject | depth map** — so you can eyeball the segmentation before
committing to a full render. The studio shows the same live.

## 2. Paint your own depth in any image editor

You don't have to derive depth from a photo. Paint a grayscale image in
Photoshop, Krita, GIMP, etc. — **white nearest, black farthest, greys between** —
and feed it straight in:

```bash
python creator.py my_depth.png --tile art.png --out stereogram.png
```

The studio can load one too (Step 1 *Load depth map…*, or Step 3 *Load depth…*,
or `--depth-in my_depth.png`).

## 3. Combine both: clip a painted depth to a photo cutout

In the [studio](studio.md) you can load a hand-painted depth and **Clip to
cutout** — keep your painted greys only inside the silhouette GrabCut found, and
flatten everything outside to "far". This marries precise hand-painting with
automatic silhouette-finding. It's simply `depth × (mask / 255)`.

## The depth map is the universal interface

Photo-cutout, hand-painting, studio depth brushes, and layout placement all
produce the same thing: a float depth array in `[0, 1]` that feeds the encoder.
Nothing downstream cares where the depth came from — which is why these
approaches mix freely.
