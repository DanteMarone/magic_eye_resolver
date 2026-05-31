---
name: magic-eye
description: >-
  Decode and generate Magic Eye images (autostereograms / single-image random-dot
  stereograms). Use this whenever the user wants to reveal the hidden picture in a
  Magic Eye or stereogram, "solve"/"see" one they can't, recover the depth map from
  an autostereogram, OR create/make a Magic Eye that hides a shape, logo, photo, or
  word inside a repeating pattern — including turning a photo or a painted depth map
  into a stereogram with a random-dot, tiled-art, or wallpaper background. Triggers
  on "magic eye", "autostereogram", "stereogram", "stereogramme", "hidden 3D image",
  "hidden picture in the pattern", "single image stereogram / SIRDS", "what's hidden
  in this", or any request to reveal/encode a hidden depth figure in a repeating image.
compatibility: Python 3 with numpy, Pillow, opencv-python (see requirements.txt). rembg is optional.
---

# Magic Eye toolkit

A Magic Eye (autostereogram) hides a 3-D figure in the horizontal *separation*
between repeats of a carrier pattern — not in the visible colours. This skill
provides command-line tools to go both directions:

- **Resolve** — recover the hidden depth map from a finished Magic Eye image.
- **Create** — generate a Magic Eye from a depth map, or straight from a photo.

The scripts are bundled in `scripts/`. Run them with the Python in the user's
environment. First-time setup: `pip install -r requirements.txt` (this folder).

## Choosing the task

- The user has a Magic Eye and wants to **see / solve / reveal** what's hidden →
  **Resolve** (`scripts/resolver.py`).
- The user wants to **make / hide / encode** a figure in a stereogram → **Create**
  (`scripts/creator.py`). Input is a depth map (white = near, black = far) or a
  photo (`--from-photo` cuts the subject out automatically).
- The user is doing hands-on, interactive editing → mention the GUI studio
  `editor.py` in the repo (`docs/studio.md`); it is human-driven (Tkinter) and not
  meant to be run by an agent.

## Resolve a Magic Eye

```bash
python scripts/resolver.py INPUT.jpg --out revealed.png
```

The output is a grayscale **depth map**: the hidden figure appears as a coherent
bright/dark region. If it comes out noisy, the carrier may be a regular grid
(undecodable — see `references/resolving.md`) or the separation band needs setting
manually with `--dmin` / `--dmax`. Full pipeline, tuning, and limitations are in
[references/resolving.md](references/resolving.md) — read it when a decode is noisy
or you need to explain how it works.

## Create a Magic Eye

From a depth map (any grayscale image, white = nearest, black = farthest):

```bash
python scripts/creator.py depth.png --out stereogram.png                 # random dots
python scripts/creator.py depth.png --tile art.png --out stereogram.png  # tiled artwork
```

From an ordinary photo (subject auto-cut-out becomes the near figure):

```bash
python scripts/creator.py photo.png --from-photo --preview-only          # inspect the cutout first
python scripts/creator.py photo.png --from-photo --tile art.png --out stereogram.png
```

Key options: `--tile IMG` (detailed artwork carrier — usually the best look),
`--background IMG` (whole image per period), `--eye-sep N` (separation/period px,
default 120), `--mu F` (depth strength 0–1, default 0.33), `--shape rounded|flat`,
`--engine grabcut|rembg`. Carrier choice, depth-map conventions, and performance
notes are in [references/creating.md](references/creating.md) — read it before
choosing a carrier or when a result looks wrong (e.g. streaky background).

## Always verify by round-tripping

The resolver is the exact inverse of the creator, so the cheapest correctness
check after generating a Magic Eye is to decode it and confirm the figure returns:

```bash
python scripts/creator.py depth.png --tile art.png --out stereo.png
python scripts/resolver.py stereo.png --out check.png   # check.png should resemble depth.png
```

Do this whenever you generate a Magic Eye for the user — if `check.png` doesn't
show the figure, the encoding parameters need adjusting (most often a smaller
`--eye-sep`, a more detailed/irregular carrier, or stronger depth contrast in the
input). Report the verification result rather than assuming success.

## Practical notes

- **Depth-map convention is absolute:** white = nearest the viewer, black =
  farthest. If the user's figure comes out inverted, invert the depth map.
- **Detailed, irregular carriers decode best.** Random dots are cleanest; busy art
  via `--tile` both looks good and round-trips. Regular grids/near-uniform images
  produce noisy results — this is inherent, not a bug.
- **Big images are slow.** The encoder is pure-Python `O(width)` per row; a
  6-megapixel image takes ~50 s. For iteration, downscale the input first, then
  render full-size once the look is right.
- **rembg is opt-in.** `--engine rembg` gives better photo cutouts but downloads an
  ML model on first run; it is not installed by default. Default `grabcut` needs
  nothing extra.
