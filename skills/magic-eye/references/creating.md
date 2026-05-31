# Creating — generate a Magic Eye from a depth map or photo

`scripts/creator.py` is the inverse of the resolver. Input is a depth map or a
photo; output is a finished autostereogram.

## Commands

```bash
# Depth map -> Magic Eye
python scripts/creator.py depth.png --out stereogram.png                 # random dots
python scripts/creator.py depth.png --tile art.png --out stereogram.png  # tiled artwork
python scripts/creator.py depth.png --background art.png --out s.png      # whole-image wallpaper

# Photo -> Magic Eye (subject cut out automatically)
python scripts/creator.py photo.png --from-photo --preview-only          # writes *_cutout_preview.png
python scripts/creator.py photo.png --from-photo --tile art.png --out stereogram.png
```

| Flag | Meaning |
|------|---------|
| `--out` | Output path (default `stereogram.png`) |
| `--tile IMG` | Tile a native-resolution slice of IMG (keeps full detail — usually best) |
| `--background IMG` | Whole image uniformly scaled to one copy per period |
| `--eye-sep N` | Carrier period / separation, px (default 120) |
| `--mu F` | Depth strength 0–1; higher = more pop (default 0.33) |
| `--from-photo` | Derive the depth map by cutting the photo's subject out |
| `--engine grabcut\|rembg` | Cutout engine (default `grabcut`) |
| `--shape rounded\|flat` | Subject relief shape (default `rounded`) |
| `--preview-only` | With `--from-photo`, write the cutout preview and stop |

## Depth-map convention

**White = nearest the viewer, black = farthest, mid-greys in between.** This is
absolute. If the figure pops the wrong way (inverted), invert the depth image. You
can hand-paint a depth map in any image editor and feed it straight in — no photo
needed.

## Choosing a carrier

- **Random dots** (default, no `--tile`/`--background`) — maximally unique, cleanest
  illusion, easiest to decode. Best default when the user has no preferred artwork.
- **`--tile IMG`** — repeats a native-resolution slice of the artwork. Detailed,
  irregular art (e.g. busy illustration) looks like a real Magic Eye poster *and*
  round-trips cleanly. Prefer this when the user supplies artwork.
- **`--background IMG`** — fits the whole image into one period. Good for a coherent
  scene per repeat, but a detailed image becomes tiny; uniform-scaled so it won't
  streak the way a naive horizontal squash would.

Regular/near-uniform carriers decode noisily — same limitation as the resolver.

## Photo cutout (`--from-photo`)

`depthmap.py` segments the foreground (near) from the background (far).

- **`grabcut`** (default) — OpenCV, self-contained, no downloads; best on a clear,
  roughly-centred subject. Always inspect the auto-written `*_cutout_preview.png`
  (original | cutout | depth) before the full render — use `--preview-only` first.
- **`rembg`** (opt-in) — much better cutouts on arbitrary photos, but downloads an ML
  model on first run; not installed by default. Only use if the user accepts that.
- **`--shape rounded`** domes the subject (relief); **`flat`** is a two-level pop-out.

## Performance

Pure-Python `O(width)` per row. A 6-megapixel photo (~2500 px wide) takes ~50 s.
Downscale the input to iterate quickly, then render full-size once. Avoid surprising
the user with a long hang on a huge image — mention it or downscale first.

## Verify

Always round-trip: `resolver.py` the generated image and confirm the figure returns
(see SKILL.md). If it doesn't, try a smaller `--eye-sep`, a more detailed `--tile`
carrier, or stronger depth contrast.
