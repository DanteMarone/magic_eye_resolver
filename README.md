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

## Creating Magic Eyes (`creator.py`)

The inverse pipeline: a depth map (or a photo) → a finished autostereogram. It
walks each row deciding which pixels must share a color, using real stereo
geometry so curved surfaces read as rounded, then fills the link-chains from a
carrier.

```bash
# From a depth map (bright = near, dark = far), random-dot carrier
python creator.py depth.png --out stereogram.png

# Use one of your own images as the visible "wallpaper" carrier
python creator.py depth.png --background art.png --out stereogram.png

# From an ordinary photo: auto cut the subject out, preview, then render
python creator.py photo.png --from-photo --preview-only   # check the cutout
python creator.py photo.png --from-photo --background art.png --out stereogram.png
```

`--from-photo` derives the depth map by segmenting the foreground subject (near)
from the background (far) and always writes a 3-panel `*_cutout_preview.png`
(original | cutout | depth) so you can eyeball the cut before committing.

**Paint your own depth.** You don't have to derive depth from a photo at all —
paint a grayscale **depth map** in any image editor (white = nearest, black =
farthest, mid-greys for in-between) and feed it straight in:
`python creator.py my_depth.png --background art.png`. The editor can also load
one (see below).

| Flag | Meaning |
|------|---------|
| `--background IMG` | Use IMG as the visible carrier (one copy per period) |
| `--tile IMG` | Tile a small texture at the period instead |
| `--eye-sep N` | Carrier period / background separation, px (default 120) |
| `--mu F` | Depth strength 0..1; higher = more pop (default 0.33) |
| `--from-photo` | Derive depth by cutting a photo's subject out |
| `--engine grabcut\|rembg` | Cutout engine (default `grabcut`) |
| `--shape rounded\|flat` | Subject relief shape (default `rounded`) |
| `--preview-only` | Write the cutout preview and stop |

**Cutout engines.** `grabcut` (default) is OpenCV GrabCut — self-contained,
pinned, downloads nothing; best on a clear, roughly-centered subject. `rembg`
(opt-in) gives far better cutouts on arbitrary photos but is **not installed by
default** because it downloads an ML model on first run; install it yourself
(`pip install rembg`) only if you accept that.

### Interactive editor (`editor.py`)

The automatic cut is a guess. `editor.py` opens a **local** window (Tkinter — no
extra dependency) to fix it by hand and choose the carrier before rendering — no
network, no ML download.

```bash
python editor.py photo.png --background art.png --out stereogram.png
```

The left canvas is the photo (drag to paint); the right canvas is the live depth
map. A toolbar gives clickable tools:

| Button / slider | Action |
|-----------------|--------|
| **Keep (green)** / **Cut (red)** | Choose the paint tool, then drag on the photo |
| **Refine cutout** | Re-run GrabCut from your strokes |
| **Shape: rounded/flat** | Toggle the subject's depth relief |
| **Carrier: random/image** | Switch between random dots and your `--background` |
| **Load depth…** | Import a depth map painted in another app (white=near, black=far) |
| **Use cutout** | Switch back to the cutout-derived depth |
| **Clip to cutout** | Keep depth only inside the subject silhouette, flatten the rest |
| **Preview** | Render a stereogram into a pop-up window |
| **Save + Quit** | Render, save stereogram + depth map, close |
| **Brush** / **Carrier brightness** | Sliders |

Start the editor straight from a painted depth with `--depth-in my_depth.png`.
Mixing both worlds is the point: paint a rough cut in Photoshop, load it here,
then `Clip to cutout` it against GrabCut's silhouette and pick a carrier.

It works at `--width` (default 900px) for responsive editing and saves the
refined `depth.png`. For a full-resolution final, feed that depth back to the
creator: `python creator.py depth.png --background art.png`.

> **Note on big images.** The row encoder is O(width); a 6-megapixel photo still
> takes ~50 s of pure-Python looping. The editor's downscaled working width
> keeps interaction snappy and is the recommended way to iterate.

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
