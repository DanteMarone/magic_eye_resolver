# Creator — turn a depth map (or photo) into a Magic Eye

`creator.py` is the inverse of the [resolver](resolver.md): it generates an
autostereogram that hides a 3-D figure. Input is a **depth map** (white = near,
black = far) or — with `--from-photo` — an ordinary photo whose subject is cut
out automatically.

## Usage

```bash
# From a depth map (bright = near, dark = far), random-dot carrier
python creator.py depth.png --out stereogram.png

# Use one of your own images as the visible carrier
python creator.py depth.png --tile art.png --out stereogram.png        # tiled (best detail)
python creator.py depth.png --background art.png --out stereogram.png   # whole image per period

# From an ordinary photo: auto-cut the subject out, preview, then render
python creator.py photo.png --from-photo --preview-only                 # check the cutout
python creator.py photo.png --from-photo --tile art.png --out stereogram.png
```

| Flag | Meaning |
|------|---------|
| `--out` | Output path (default `stereogram.png`) |
| `--background IMG` | Use IMG as the visible carrier, uniformly scaled to one copy per period |
| `--tile IMG` | Tile a native-resolution slice of IMG at the period (keeps full detail) |
| `--eye-sep N` | Carrier period / background separation, px (default 120) |
| `--mu F` | Depth strength 0..1; higher = more pop (default 0.33) |
| `--from-photo` | Derive the depth map by cutting a photo's subject out |
| `--engine grabcut\|rembg` | Cutout engine for `--from-photo` (default `grabcut`) |
| `--shape rounded\|flat` | Subject relief shape (default `rounded`) |
| `--preview-only` | With `--from-photo`, write the cutout preview and stop |

For depth-from-photo details (engines, shapes, painting your own depth) see
[depth-maps.md](depth-maps.md).

## How the encoding works

The algorithm is Thimbleby–Witkin–Inwood (1994). For each row it walks
left-to-right and records, per pixel, which earlier pixel it must **share a
colour with** — the pair the eyes fuse — then floods each link-chain from the
carrier.

1. **Depth → separation** (`depth_to_separation`) — real stereo geometry,
   `eye_sep·(1−µ·Z)/(2−µ·Z)`, so separation shrinks non-linearly as a surface
   approaches the viewer and curved shapes read as genuinely rounded rather than
   flat planes. `µ` (`--mu`) is the depth-of-field strength.
2. **Constraint links** — for each pixel, link the left/right pixel of its
   separation as "same colour", with a **bounded hidden-surface test** so a near
   surface only hides links over the small span it could geometrically block.
   That keeps the row pass `O(width × depth_of_field)` instead of `O(width²)`.
3. **Fill** — left-to-right, a self-linked pixel seeds from the carrier; every
   other copies its already-coloured left partner, propagating colours rightward.

## Carriers

The carrier is the visible surface. Three styles:

- **Random dots** (default) — maximally unique, the cleanest illusion and easiest
  to decode.
- **Tiled image** (`--tile`) — a native-resolution slice of your art repeated at
  the period. Best-looking for detailed art; the artwork stays recognisable.
- **Background / wallpaper image** (`--background`) — the whole image uniformly
  scaled so one copy spans a period, then tiled vertically. Uniform scaling
  matters: squashing a wide image straight to `eye_sep` px shears it into vertical
  streaks; scaling by aspect keeps it intact, though a detailed image becomes very
  small at one-copy-per-period.

> **Tip.** For a busy, irregular image (e.g. psychedelic art), `--tile` gives the
> most striking result *and* decodes cleanly. Regular/near-uniform images decode
> noisier — the same limitation noted for the [resolver](resolver.md).

## Performance

The row encoder is `O(width)` per row but pure Python; a 6-megapixel photo
(~2500 px wide) still takes ~50 s. To iterate quickly, work at a reduced width
(the [studio](studio.md) does this automatically) and only render full-resolution
once you are happy with the depth and carrier.
