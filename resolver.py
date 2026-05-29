"""Magic Eye (autostereogram) resolver.

Recovers the hidden DEPTH image from an autostereogram. A Magic Eye encodes a
figure not in color (the visible artwork is often a decoy) but in the tiny
horizontal shifts of a repeating carrier pattern: the local horizontal
"separation" between repeats varies with depth. When you cross your eyes, your
brain reads those separation differences as a 3-D shape. This program recovers
that shape computationally.

Pipeline:
  1. Grayscale + HIGH-PASS to discard the low-frequency color/brightness decoy
     and keep only the high-frequency carrier that actually carries depth.
  2. Build a matching cost VOLUME: for each candidate separation d, how well
     does each pixel match the pixel d columns to its left.
  3. SEMI-GLOBAL MATCHING: aggregate that cost along several directions with a
     smoothness penalty, so the recovered separation field is piecewise-smooth
     (coherent figure) instead of per-pixel noise.
  4. The winning separation per pixel IS the depth map -> the hidden figure.

Usage:
    python resolver.py <image_path> [--out result.png]
                        [--dmin N --dmax N]   # separation search band (px)
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image


def load_grayscale(path: str | Path) -> np.ndarray:
    """Load an image and return it as a float64 grayscale array in [0, 1]."""
    img = Image.open(path).convert("L")
    return np.asarray(img, dtype=np.float64) / 255.0


def _box_blur(a: np.ndarray, radius: int) -> np.ndarray:
    """Separable box blur via cumulative sums (handles non-finite safely)."""
    if radius <= 0:
        return a
    a = np.where(np.isfinite(a), a, 1e9)
    k = 2 * radius + 1

    def blur_axis(x: np.ndarray, axis: int) -> np.ndarray:
        pad = [(0, 0), (0, 0)]
        pad[axis] = (radius, radius)
        xp = np.pad(x, pad, mode="edge")
        cs = np.cumsum(xp, axis=axis)
        zero = np.zeros_like(np.take(cs, [0], axis=axis))
        cs = np.concatenate([zero, cs], axis=axis)
        sl_hi = [slice(None)] * 2
        sl_lo = [slice(None)] * 2
        sl_hi[axis] = slice(k, None)
        sl_lo[axis] = slice(None, -k)
        return (cs[tuple(sl_hi)] - cs[tuple(sl_lo)]) / k

    return blur_axis(blur_axis(a, 1), 0)


def crop_borders(gray: np.ndarray, rel_thresh: float = 0.3
                 ) -> tuple[np.ndarray, tuple[slice, slice]]:
    """Trim low-variance edge rows/columns (solid frames) before decoding.

    The carrier pattern has high local variance everywhere it appears; a solid
    border (the black frame on these samples) has near-zero variance and no
    pattern to match, so it decodes to garbage and skews the band estimate.
    We measure per-row and per-column standard deviation and keep the bounding
    box of rows/cols whose std exceeds `rel_thresh` x the median std -- which
    trims uniform margins while leaving the interior intact.
    """
    def content_span(std: np.ndarray) -> slice:
        keep = std > rel_thresh * np.median(std)
        idx = np.flatnonzero(keep)
        if idx.size == 0:
            return slice(0, std.size)
        return slice(int(idx[0]), int(idx[-1]) + 1)

    rows = content_span(gray.std(axis=1))
    cols = content_span(gray.std(axis=0))
    return gray[rows, cols], (rows, cols)


def high_pass(gray: np.ndarray, radius: int = 20) -> np.ndarray:
    """Remove low-frequency color/brightness bias, keeping the carrier pattern.

    The hidden figure is sometimes ALSO painted into the artwork as a slow
    color/brightness gradient (a decoy). That low-frequency bias both distracts
    the human eye and corrupts stereo matching. Subtracting a heavily-blurred
    copy leaves only the high-frequency carrier dots that encode true depth.
    """
    return gray - _box_blur(gray, radius)


def estimate_separation_band(gray: np.ndarray) -> tuple[int, int]:
    """Estimate a plausible [dmin, dmax] separation band from autocorrelation.

    On the high-passed image, the horizontal autocorrelation has peaks at the
    separations the carrier repeats with. The figure and background usually sit
    at different separations, so we bracket the strongest peaks with margin.
    """
    hp = high_pass(gray)
    profile = (hp - hp.mean()).mean(axis=0)
    profile -= profile.mean()
    corr = np.correlate(profile, profile, mode="full")
    corr = corr[corr.size // 2:]
    corr = corr / (corr[0] + 1e-12)

    width = gray.shape[1]
    lo, hi = 20, min(width // 3, 160)
    band = corr[lo:hi]
    # peaks above a fraction of the strongest peak in range
    thresh = 0.4 * band.max()
    peaks = [lo + i for i in range(1, len(band) - 1)
             if band[i] > band[i - 1] and band[i] >= band[i + 1]
             and band[i] >= thresh]
    if not peaks:
        peaks = [lo + int(np.argmax(band))]
    # Bracket all strong peaks with margin. We deliberately keep the band wide:
    # the hidden figure's separation can sit well above the carrier's
    # fundamental (e.g. beyond 2x it), so narrowing the upper bound risks
    # cutting off the very separation the figure lives at.
    dmin = max(16, min(peaks) - 8)
    dmax = max(peaks) + 8
    return dmin, dmax


def build_cost_volume(
    hp: np.ndarray, dmin: int, dmax: int, window: int = 3
) -> np.ndarray:
    """Cost volume C[y, x, k]: matching cost of pixel (y,x) vs (y, x-d).

    Low cost means "the carrier repeats with separation d here". We use
    absolute difference, lightly box-aggregated over a small window so the cost
    reflects a neighborhood rather than a single noisy pixel. Columns with no
    valid left-hand partner get a high constant cost.
    """
    h, w = hp.shape
    depths = range(dmin, dmax + 1)
    cost = np.empty((h, w, len(depths)), dtype=np.float64)
    for k, d in enumerate(depths):
        sad = np.full((h, w), 1.0)
        sad[:, d:] = np.abs(hp[:, d:] - hp[:, : w - d])
        cost[:, :, k] = _box_blur(sad, window)
    return cost


def _aggregate_direction(cost: np.ndarray, axis: int, reverse: bool,
                         p1: float, p2: float) -> np.ndarray:
    """One SGM pass along a scanline direction (vectorized over the other axis).

    L(p, d) = C(p, d) + min( L(p-,d),  L(p-,d±1)+P1,  min_k L(p-,k)+P2 )
              - min_k L(p-, k)
    The small penalty P1 allows gradual depth slopes; the larger P2 caps the
    cost of a depth discontinuity (object edge). Subtracting the running min
    just keeps numbers from growing without bound.
    """
    h, w, _ = cost.shape
    L = np.zeros_like(cost)
    n = w if axis == 1 else h
    start = n - 1 if reverse else 0
    if axis == 1:
        L[:, start, :] = cost[:, start, :]
    else:
        L[start, :, :] = cost[start, :, :]

    order = range(n - 2, -1, -1) if reverse else range(1, n)
    for i in order:
        j = i + 1 if reverse else i - 1
        prev = L[:, j, :] if axis == 1 else L[j, :, :]   # (N, D)
        m = prev.min(axis=-1, keepdims=True)
        left = np.full_like(prev, 1e18)
        left[..., 1:] = prev[..., :-1] + p1
        right = np.full_like(prev, 1e18)
        right[..., :-1] = prev[..., 1:] + p1
        best = np.minimum(np.minimum(prev, left), np.minimum(right, m + p2))
        cur = (cost[:, i, :] if axis == 1 else cost[i, :, :]) + best - m
        if axis == 1:
            L[:, i, :] = cur
        else:
            L[i, :, :] = cur
    return L


def semi_global_match(cost: np.ndarray, p1: float = 0.1,
                      p2: float = 2.0) -> np.ndarray:
    """Aggregate the cost volume along 4 directions and return summed cost."""
    return (
        _aggregate_direction(cost, 1, False, p1, p2)
        + _aggregate_direction(cost, 1, True, p1, p2)
        + _aggregate_direction(cost, 0, False, p1, p2)
        + _aggregate_direction(cost, 0, True, p1, p2)
    )


def normalize_to_image(disparity: np.ndarray) -> np.ndarray:
    """Stretch the disparity map to a 0-255 uint8 image for viewing."""
    lo, hi = np.percentile(disparity, 2), np.percentile(disparity, 98)
    if hi <= lo:
        hi = lo + 1.0
    norm = np.clip((disparity - lo) / (hi - lo), 0.0, 1.0)
    return (norm * 255).astype(np.uint8)


def resolve(path: str | Path, dmin: int | None = None,
            dmax: int | None = None) -> np.ndarray:
    """Full pipeline: image path -> revealed depth image (uint8 array)."""
    gray = load_grayscale(path)
    full_shape = gray.shape
    gray, _ = crop_borders(gray)
    if gray.shape != full_shape:
        print(f"Cropped borders: {full_shape} -> {gray.shape}")
    if dmin is None or dmax is None:
        dmin, dmax = estimate_separation_band(gray)
    print(f"Searching separations {dmin}-{dmax}px")

    hp = high_pass(gray)
    cost = build_cost_volume(hp, dmin, dmax)
    summed = semi_global_match(cost)
    disparity = float(dmin) + np.argmin(summed, axis=2).astype(np.float64)
    disparity = _box_blur(disparity, 3)   # final smoothing of the depth field
    # The leftmost dmax columns have no (or only a partial) left-hand partner to
    # match against, so their disparity is meaningless. Trim them off so the
    # un-decodable margin doesn't appear as a noisy stripe in the result.
    disparity = disparity[:, dmax:]
    return normalize_to_image(disparity)


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve a Magic Eye image.")
    parser.add_argument("image", help="Path to the autostereogram image")
    parser.add_argument("--out", default="result.png", help="Output image path")
    parser.add_argument("--dmin", type=int, default=None,
                        help="Min separation (px); auto-estimated if omitted")
    parser.add_argument("--dmax", type=int, default=None,
                        help="Max separation (px); auto-estimated if omitted")
    args = parser.parse_args()

    result = resolve(args.image, args.dmin, args.dmax)
    Image.fromarray(result).save(args.out)
    print(f"Saved revealed depth image to {args.out}")


if __name__ == "__main__":
    main()
