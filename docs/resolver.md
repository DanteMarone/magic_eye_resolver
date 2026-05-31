# Resolver — recover the hidden depth from a Magic Eye

`resolver.py` takes an autostereogram (Magic Eye) image and recovers the hidden
**depth map** — the 3-D figure encoded in it — without you having to cross your
eyes.

A Magic Eye hides a figure not in the visible artwork (often a deliberate
**color decoy**) but in the tiny horizontal shifts of a repeating carrier
pattern: the local horizontal *separation* between repeats varies with depth.
When you cross your eyes, your brain fuses neighbouring repeats and reads those
separation differences as a 3-D shape. The resolver recovers that shape
computationally by treating the image as a self-referential stereo pair.

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

## Pipeline

The resolver solves the self-referential stereo problem with techniques from
stereo matching:

1. **Grayscale + high-pass filter** (`high_pass`) — subtracts a heavily-blurred
   copy to discard the low-frequency colour/brightness decoy, so matching keys on
   the high-frequency carrier that actually encodes depth.
2. **Border crop** (`crop_borders`) — trims low-variance solid frames that would
   otherwise decode to garbage and skew the band estimate.
3. **Separation band estimation** (`estimate_separation_band`) — horizontal
   autocorrelation locates the separations the carrier repeats at, bracketing the
   search range `[dmin, dmax]`.
4. **Cost volume** (`build_cost_volume`) — for every candidate separation `d`,
   how well each pixel matches the pixel `d` columns to its left (box-aggregated
   absolute difference).
5. **Semi-Global Matching** (`semi_global_match`) — aggregates the cost along
   four directions with a smoothness penalty (P1 for gradual slopes, P2 capping
   discontinuities), turning noisy per-pixel guesses into a coherent,
   piecewise-smooth depth field. This is the step that makes the figure emerge
   instead of salt-and-pepper noise.
6. **Margin trim** — the leftmost `dmax` columns have no left-hand partner to
   match against, so that un-decodable strip is cropped off.

The winning separation per pixel *is* the depth map — the hidden figure.

## Limitations

The decoder relies on each carrier patch being **locally unique** — the way
proper random-dot autostereograms are built. Images whose carrier is a
**regular, repeating grid** (rather than random dots) have no unique pixel
correspondence: every position matches equally well at the grid period in both
axes, so no local/SGM matcher can disambiguate them. Those images decode to
noise. This is a fundamental property of the input, not a tuning issue.

When auto-estimation produces a noisy result on a new image, the first thing to
try is a manual `--dmin` / `--dmax` bracketing that image's fundamental period.

## Round-trip with the creator

The resolver is the inverse of [`creator.py`](creator.md). A good way to verify a
generated Magic Eye is to resolve it and confirm the figure comes back:

```bash
python creator.py depth.png --tile art.png --out stereo.png
python resolver.py stereo.png --out recovered.png   # should match depth.png
```
