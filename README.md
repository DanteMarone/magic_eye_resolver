# Magic Eye Resolver

Recover the hidden depth image from a Magic Eye (autostereogram) without
crossing your eyes.

A Magic Eye hides a figure not in the visible artwork (which is often a
deliberate **color decoy**) but in the tiny horizontal shifts of a repeating
carrier pattern: the local horizontal *separation* between repeats varies with
depth. When you cross your eyes, your brain fuses neighboring repeats and reads
those separation differences as a 3-D shape. This tool recovers that shape
computationally.

## How it works

The pipeline treats the image as a self-referential stereo pair and solves it
with techniques from stereo matching:

1. **Grayscale + high-pass filter** — discards the low-frequency color/brightness
   decoy so matching keys on the high-frequency carrier that actually encodes
   depth.
2. **Separation band estimation** — horizontal autocorrelation locates the
   separations the carrier repeats at, bracketing the search range.
3. **Cost volume** — for every candidate separation `d`, how well each pixel
   matches the pixel `d` columns to its left (box-aggregated absolute
   difference).
4. **Semi-Global Matching (SGM)** — aggregates the cost along four directions
   with a smoothness penalty, turning noisy per-pixel guesses into a coherent,
   piecewise-smooth depth field. This is the step that makes the figure emerge
   instead of salt-and-pepper noise.
5. **Margin trim** — the leftmost columns have no left-hand partner to match
   against, so that un-decodable strip is cropped off.

The winning separation per pixel *is* the depth map — the hidden figure.

## Usage

```bash
pip install -r requirements.txt

# Fully automatic
python resolver.py path/to/magic_eye.jpg --out result.png

# Manual separation band for stubborn images
python resolver.py path/to/magic_eye.jpg --dmin 38 --dmax 122
```

Output is a grayscale depth map: brighter = one depth plane, darker = another,
with the hidden figure as a coherent region.

| Flag | Meaning |
|------|---------|
| `--out` | Output path (default `result.png`) |
| `--dmin` / `--dmax` | Separation search band in pixels; auto-estimated if omitted |

## Limitations

The decoder relies on each carrier patch being **locally unique** — the way
proper random-dot autostereograms are built. Images whose carrier is a
**regular, repeating grid** (rather than random dots) have no unique pixel
correspondence: every position matches equally well at the grid period in both
axes, so no local/SGM matcher can disambiguate them. Those images decode to
noise. This is a fundamental property of the input, not a tuning issue.

When auto-estimation produces a noisy result on a new image, the first thing to
try is a manual `--dmin`/`--dmax` bracketing that image's fundamental period.

## Requirements

- Python 3.x
- numpy, Pillow (pinned in `requirements.txt`)
