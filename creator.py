"""Magic Eye (autostereogram) creator.

The inverse of resolver.py. Given a DEPTH image (the hidden figure: bright =
near, dark = far), this synthesizes a random-dot autostereogram that encodes it.

How the encoding works:
  A Magic Eye hides a figure in the horizontal SEPARATION between repeats of a
  carrier pattern. To build one we walk each row left-to-right and, for every
  pixel, decide which earlier pixel it must SHARE A COLOR with: the two pixels
  the viewer's eyes will fuse. Pixels at greater depth sit farther apart; pixels
  at lesser depth sit closer. We record those "must match" links, then fill each
  chain of linked pixels with a single random color. Crossing your eyes fuses
  each linked pair, and the varying separation reads back as 3-D.

Pipeline:
  1. Load the depth image, normalize to [0, 1].
  2. Per pixel, map depth -> horizontal separation (the eye-geometry step).
  3. Per row, link the left/right pixel of each separation as "same color",
     respecting occlusion (a nearer surface hides links that pass behind it).
  4. Flood each link-chain with one random color (random dots) or sample a
     texture tile, producing the final autostereogram.

Usage:
    python creator.py <depth_or_photo> [--out stereogram.png]
                      [--eye-sep N]      # carrier period / max separation (px)
                      [--mu F]           # depth strength, 0..1 (default 0.33)
                      [--background IMG] # use IMG as the visible carrier image
                      [--tile IMG]       # small texture tiled at the period
                      [--from-photo]     # derive depth by cutting out a photo
                      [--engine E]       # grabcut (default) | rembg (opt-in ML)
                      [--shape S]        # rounded (default) | flat
                      [--preview-only]   # write the cutout preview and stop
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image


def load_depth(path: str | Path) -> np.ndarray:
    """Load a depth image as float64 in [0, 1]; bright = near, dark = far."""
    img = Image.open(path).convert("L")
    return np.asarray(img, dtype=np.float64) / 255.0


def depth_to_separation(depth: np.ndarray, eye_sep: int, mu: float) -> np.ndarray:
    """Map normalized depth in [0, 1] to horizontal separation in pixels.

    This is THE decision that defines how the finished illusion looks, so it's
    left for you to implement (see the request below). `depth` is a float64
    array in [0, 1] (1 = nearest to the viewer, 0 = farthest). `eye_sep` is the
    carrier period in pixels (the separation of the far background plane). `mu`
    in [0, 1] is the depth-of-field strength: how much nearer objects pull
    their separation in toward the eyes.

    Return an int array (same shape as `depth`) of separations in pixels.
    """
    # Real stereo geometry: separation shrinks nonlinearly toward the eyes as
    # depth increases, modelling actual eye convergence so curved surfaces read
    # as genuinely rounded rather than stacked flat planes.
    return np.round(eye_sep * (1 - mu * depth) / (2 - mu * depth)).astype(int)


def make_carrier(height: int, eye_sep: int, bg_path: str | None,
                 tile_path: str | None) -> np.ndarray:
    """Build the source colors for the leftmost `eye_sep` columns of each row.

    Three carrier styles, in priority order:
      - background image: the image UNIFORMLY scaled (no horizontal stretch) so
        one full-width copy spans a period, then tiled vertically -> a
        "wallpaper" stereogram whose visible surface IS your image. Uniform
        scaling matters: squashing a wide image straight to eye_sep px shears its
        detail into vertical streaks; scaling by aspect keeps the artwork intact.
      - texture tile: a native-resolution slice repeated (tiled) at the period,
        for art whose detail you want shown 1:1 rather than fit-to-period.
      - random dots (default): maximally unique carrier, the cleanest illusion.
    Returns an (height, eye_sep, 3) uint8 array sampled per row.
    """
    if bg_path is not None:
        src = Image.open(bg_path).convert("RGB")
        strip_h = max(1, round(eye_sep * src.height / src.width))
        strip = np.asarray(src.resize((eye_sep, strip_h)), dtype=np.uint8)
        rows = np.arange(height) % strip_h
        return strip[rows]
    if tile_path is not None:
        tile = np.asarray(Image.open(tile_path).convert("RGB"), dtype=np.uint8)
        th, tw = tile.shape[:2]
        cols = np.arange(eye_sep) % tw
        rows = np.arange(height) % th
        return tile[np.ix_(rows, cols)]
    rng = np.random.default_rng()
    return rng.integers(0, 256, size=(height, eye_sep, 3), dtype=np.uint8)


def render(depth: np.ndarray, eye_sep: int, mu: float,
           bg_path: str | None, tile_path: str | None,
           carrier: np.ndarray | None = None) -> np.ndarray:
    """Synthesize the autostereogram from a depth map (Thimbleby et al. 1994).

    For each row we record, per pixel, which earlier pixel it must SHARE A COLOR
    with (the pair the eyes fuse), then flood each link-chain from the carrier.
    Occlusion is handled by a *bounded* hidden-surface test: a near surface hides
    a link only over the small span where it could geometrically block the view.
    That keeps the row pass O(w x depth_of_field) instead of O(w^2).
    """
    h, w = depth.shape
    sep = depth_to_separation(depth, eye_sep, mu)
    # A caller (e.g. the editor) may pass a ready-made carrier; otherwise build
    # one from the background/tile options.
    if carrier is None:
        carrier = make_carrier(h, eye_sep, bg_path, tile_path)
    out = np.zeros((h, w, 3), dtype=np.uint8)
    E = float(eye_sep)

    for y in range(h):
        Z = depth[y]
        srow = sep[y]
        same = np.arange(w)
        for x in range(w):
            s = int(srow[x])
            left = x - s // 2
            right = left + s
            if left < 0 or right >= w:
                continue
            # Hidden-surface removal: a point t columns from x could occlude this
            # link only until the view ray clears depth `zt`. Once zt reaches the
            # near clip (>= 1) nothing further can block it, so the loop is short.
            visible = True
            t = 1
            while True:
                zt = Z[x] + 2.0 * (2.0 - mu * Z[x]) * t / (mu * E)
                if zt >= 1.0:
                    break
                xl, xr = x - t, x + t
                if xl >= 0 and xr < w and (Z[xl] >= zt or Z[xr] >= zt):
                    visible = False
                    break
                t += 1
            if visible:
                same[right] = left
        # Fill left-to-right: links point left (same[right] = left), so each
        # left partner is already colored before the right pixel copies it. A
        # self-linked pixel seeds from the carrier.
        for x in range(w):
            if same[x] == x:
                out[y, x] = carrier[y, x % eye_sep]
            else:
                out[y, x] = out[y, same[x]]
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a Magic Eye image.")
    parser.add_argument("source", help="Depth/figure image, or a photo with "
                                       "--from-photo")
    parser.add_argument("--out", default="stereogram.png", help="Output path")
    parser.add_argument("--eye-sep", type=int, default=120,
                        help="Carrier period / background separation (px)")
    parser.add_argument("--mu", type=float, default=0.33,
                        help="Depth strength, 0..1 (default 0.33)")
    parser.add_argument("--background", default=None,
                        help="Image used as the visible carrier (wallpaper)")
    parser.add_argument("--tile", default=None,
                        help="Small texture tiled at the period")
    parser.add_argument("--from-photo", action="store_true",
                        help="Derive the depth map by cutting a photo out")
    parser.add_argument("--engine", choices=("grabcut", "rembg"),
                        default="grabcut",
                        help="Cutout engine for --from-photo (default grabcut)")
    parser.add_argument("--shape", choices=("rounded", "flat"),
                        default="rounded",
                        help="Subject depth shape for --from-photo")
    parser.add_argument("--preview-only", action="store_true",
                        help="With --from-photo, write the cutout preview and "
                             "stop (no stereogram)")
    args = parser.parse_args()

    if args.from_photo:
        # Lazy import so plain depth-map use needs no OpenCV.
        import depthmap
        depth, rgb, mask = depthmap.photo_to_depth(
            args.source, args.engine, args.shape)
        preview_path = str(Path(args.out).with_suffix("")) + "_cutout_preview.png"
        depthmap.make_preview(rgb, mask, depth).save(preview_path)
        print(f"Saved cutout preview to {preview_path}")
        if args.preview_only:
            return
    else:
        depth = load_depth(args.source)

    result = render(depth, args.eye_sep, args.mu, args.background, args.tile)
    Image.fromarray(result).save(args.out)
    print(f"Saved autostereogram to {args.out}")


if __name__ == "__main__":
    main()
