"""Turn a regular photo into a depth map for creator.py.

A Magic Eye needs a DEPTH image (bright = near, dark = far). This module derives
one from an ordinary photo by cutting the foreground subject out and treating it
as the near plane, with the background pushed far. Two cutout engines:

  - grabcut (default): OpenCV GrabCut. Self-contained, pinned, downloads
    nothing. Works best on a clear subject roughly centered in frame.
  - rembg (opt-in): U^2-Net ML matting. Much better on arbitrary photos, but it
    pulls onnxruntime and downloads a model from the internet on first run.
    It is NOT a declared dependency. Install it yourself only if you accept
    that:  pip install rembg

The cut-out subject can be shaped two ways:
  - rounded (default): a distance transform domes the subject toward the viewer,
    so it reads as a rounded relief rather than a flat sticker.
  - flat: subject on one near plane, background on one far plane.
"""

from __future__ import annotations

import numpy as np
from PIL import Image
import cv2


def load_rgb(path: str) -> np.ndarray:
    """Load an image as an (H, W, 3) uint8 RGB array."""
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.uint8)


def grabcut_mask(rgb: np.ndarray, iters: int = 5, margin: float = 0.08
                 ) -> np.ndarray:
    """Segment the foreground with OpenCV GrabCut, auto-seeded by a frame inset.

    GrabCut needs an initial guess of where the subject is. With no user box we
    assume the subject occupies the centre and seed it with a rectangle inset by
    `margin` on every side, then let GrabCut refine the boundary. Returns a
    uint8 mask: 255 = foreground, 0 = background.
    """
    h, w = rgb.shape[:2]
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    mask = np.zeros((h, w), np.uint8)
    rect = (int(w * margin), int(h * margin),
            int(w * (1 - 2 * margin)), int(h * (1 - 2 * margin)))
    bgd = np.zeros((1, 65), np.float64)
    fgd = np.zeros((1, 65), np.float64)
    cv2.grabCut(bgr, mask, rect, bgd, fgd, iters, cv2.GC_INIT_WITH_RECT)
    fg = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0)
    return fg.astype(np.uint8)


def rembg_mask(rgb: np.ndarray) -> np.ndarray:
    """Segment the foreground with rembg (U^2-Net), if the user installed it.

    rembg is intentionally NOT a declared dependency: it downloads an ML model
    on first use. We import it lazily and, if it's missing, stop with clear
    instructions instead of silently fetching anything.
    """
    try:
        from rembg import remove
    except ImportError as exc:
        raise SystemExit(
            "rembg is not installed. It downloads an ML model on first run.\n"
            "If you accept that, install it yourself:  pip install rembg\n"
            "Otherwise use the default engine (--engine grabcut), which "
            "downloads nothing."
        ) from exc
    rgba = np.asarray(remove(Image.fromarray(rgb)))
    alpha = rgba[..., 3] if rgba.shape[-1] == 4 else np.full(rgb.shape[:2], 255)
    return (alpha > 127).astype(np.uint8) * 255


def mask_to_depth(mask: np.ndarray, shape: str = "rounded",
                  blur: float = 2.0) -> np.ndarray:
    """Convert a foreground mask into a float64 depth map in [0, 1].

    `flat` gives a two-level pop-out. `rounded` runs a distance transform so the
    subject's interior (farthest from any edge) is nearest the viewer and falls
    off toward the silhouette — a relief-carving look. A light Gaussian blur
    removes stair-stepping that would otherwise show as banding in the result.
    """
    fg = (mask > 127).astype(np.uint8)
    if shape == "flat":
        depth = fg.astype(np.float64)
    else:
        dist = cv2.distanceTransform(fg * 255, cv2.DIST_L2, 5)
        peak = float(dist.max())
        dist = dist / peak if peak > 0 else dist
        depth = np.sqrt(dist)  # sqrt -> dome-like falloff, not a sharp cone
    if blur > 0:
        k = max(1, int(blur * 2)) * 2 + 1
        depth = cv2.GaussianBlur(depth, (k, k), blur)
    return np.clip(depth, 0.0, 1.0)


def photo_to_depth(path: str, engine: str = "grabcut", shape: str = "rounded"
                   ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Photo path -> (depth in [0,1], original RGB, foreground mask)."""
    rgb = load_rgb(path)
    mask = rembg_mask(rgb) if engine == "rembg" else grabcut_mask(rgb)
    depth = mask_to_depth(mask, shape)
    return depth, rgb, mask


def make_preview(rgb: np.ndarray, mask: np.ndarray, depth: np.ndarray
                 ) -> Image.Image:
    """3-panel preview: original | cut-out subject | derived depth map.

    Lets you eyeball the segmentation before committing to a full render.
    """
    h, w = mask.shape
    fg = (mask > 127)[..., None]
    cutout = np.where(fg, rgb, 0).astype(np.uint8)
    depth_rgb = np.repeat((depth * 255).astype(np.uint8)[..., None], 3, axis=2)
    gap = np.full((h, 8, 3), 255, dtype=np.uint8)
    strip = np.concatenate([rgb, gap, cutout, gap, depth_rgb], axis=1)
    return Image.fromarray(strip)
