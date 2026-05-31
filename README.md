# Magic Eye Resolver & Studio

A local toolkit for **Magic Eye** (autostereogram) images: **resolve** the hidden
3-D figure out of one, **create** one from a depth map or photo, and an
interactive **studio** to do it all by hand.

A Magic Eye hides a figure not in the visible artwork (often a deliberate
**color decoy**) but in the tiny horizontal shifts of a repeating carrier
pattern: the local *separation* between repeats varies with depth. Crossing your
eyes fuses neighbouring repeats and your brain reads those shifts as a 3-D shape.

Three tools, all offline (no network, no ML download unless you opt in):

| Tool | What it does | Docs |
|------|--------------|------|
| `resolver.py` | Magic Eye → hidden depth map (stereo matching) | [docs/resolver.md](docs/resolver.md) |
| `creator.py` | Depth map or photo → Magic Eye | [docs/creator.md](docs/creator.md) |
| `editor.py` | Interactive studio: cut out, sculpt depth, pick carrier, render | [docs/studio.md](docs/studio.md) |

## Getting started

```bash
pip install -r requirements.txt
```

**Resolve** a Magic Eye (recover the hidden figure):

```bash
python resolver.py path/to/magic_eye.jpg --out result.png
```

**Create** a Magic Eye from a depth map (white = near, black = far):

```bash
python creator.py depth.png --tile art.png --out stereogram.png
```

…or straight from a photo (the subject is cut out automatically):

```bash
python creator.py photo.png --from-photo --tile art.png --out stereogram.png
```

**Studio** — do the whole thing interactively (load everything in-window):

```bash
python editor.py
```

## Features

- **Resolver** — high-pass + autocorrelation band estimation + Semi-Global
  Matching to recover a clean, piecewise-smooth depth map. → [docs](docs/resolver.md)
- **Creator** — Thimbleby row encoder with real stereo-geometry depth, bounded
  occlusion, and three carrier styles (random dots, tiled art, wallpaper).
  → [docs](docs/creator.md)
- **Depth maps** — derive from a photo (GrabCut, or opt-in rembg), paint your own
  in any editor, or combine the two (clip a painted depth to a cutout).
  → [docs](docs/depth-maps.md)
- **Studio** — a 5-step wizard: Source → Cutout → Depth → Background → Preview.
  Paintable cutout *and* depth, zoom/pan with a cursor brush ring, undo/redo
  (Ctrl+Z/Y), live separation preview, subject placement (move + scale) on a
  background, and 0–100 sliders throughout. → [docs](docs/studio.md)

## Documentation

- [docs/resolver.md](docs/resolver.md) — recovering depth from a Magic Eye
- [docs/creator.md](docs/creator.md) — generating a Magic Eye, carriers, performance
- [docs/depth-maps.md](docs/depth-maps.md) — photo cutout, shapes, painting depth
- [docs/studio.md](docs/studio.md) — the interactive studio, step by step

These docs are kept in sync with the code: every feature is documented when added
and updated whenever its behaviour changes (see [CONTRIBUTING.md](CONTRIBUTING.md)).

## Requirements

- Python 3.x
- `numpy`, `Pillow`, `opencv-python` (pinned in `requirements.txt`)
- `rembg` is **optional / opt-in** (better photo cutouts, but downloads an ML
  model on first run) — install it yourself only if you accept that.

## Limitations

The resolver relies on each carrier patch being **locally unique** (true random
dots). Carriers that are a **regular, repeating grid** have no unique
correspondence and decode to noise — a property of the input, not a tuning issue.
The pure-Python creator is `O(width)` per row; a 6-megapixel image takes ~50 s, so
the studio edits at a reduced width and you render full-size only at the end.
