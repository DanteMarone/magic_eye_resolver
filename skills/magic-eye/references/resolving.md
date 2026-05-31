# Resolving — recover the hidden depth from a Magic Eye

`scripts/resolver.py` treats the autostereogram as a self-referential stereo pair
and recovers the hidden depth map.

## Command

```bash
python scripts/resolver.py INPUT.(jpg|png) --out revealed.png
python scripts/resolver.py INPUT.jpg --dmin 38 --dmax 122   # manual separation band
```

| Flag | Meaning |
|------|---------|
| `--out` | Output path (default `result.png`) |
| `--dmin` / `--dmax` | Separation search band in px; auto-estimated if omitted |

Output is a grayscale depth map — the hidden figure is the coherent bright/dark
region.

## Pipeline (how it works)

1. **Grayscale + high-pass** — removes the low-frequency colour/brightness decoy so
   matching keys on the carrier that actually encodes depth.
2. **Border crop** — trims solid low-variance frames that would skew estimation.
3. **Separation band estimation** — autocorrelation finds the carrier's repeat
   separations, bracketing the search range.
4. **Cost volume** — for each candidate separation `d`, how well each pixel matches
   the pixel `d` columns left.
5. **Semi-Global Matching** — aggregates cost over four directions with a smoothness
   penalty, turning per-pixel noise into a coherent figure.
6. **Margin trim** — drops the leftmost columns that have no left partner.

## When a decode is noisy

- **Set the band manually.** Auto-estimation can miss; try `--dmin`/`--dmax`
  bracketing the carrier's fundamental period (eyeball the repeat width in px).
- **Regular-grid carriers are undecodable.** If the carrier is a repeating grid or
  tiled motif rather than random-ish texture, every position matches equally well at
  the grid period — no matcher can disambiguate it, and the result is noise. This is
  a property of the input, not a tuning failure; say so rather than retrying forever.
- **Low contrast / heavy JPEG artifacts** weaken the carrier signal; results degrade
  gracefully but may be faint.
