# 🎧 beetroot

> **Fully vibe coded by [Claude Sonnet 4.6](https://anthropic.com) (Anthropic). Every line of Python in this project was written by an AI — no human code was harmed in the making of this mix.**

beetroot is a command-line auto-DJ that analyzes a folder of music files, detects the BPM of every track, orders them along a BPM curve of your choosing, and stitches them into a single seamless MP3 with smooth crossfade transitions.

---

## Features

- **BPM detection** — uses [librosa](https://librosa.org/) with a multi-pass beat tracker and octave normalization to reliably detect tempo across genres
- **BPM curve shaping** — four modes for controlling how the energy arc of your mix evolves over time
- **Smooth crossfades** — independent fade-out and fade-in with configurable overlap so you always hear both songs during the transition
- **Max song length cap** — trim long tracks and fade into the next one at a set duration
- **Optional time-stretch transitions** — tempo-morph between songs at BPM boundaries using [Rubber Band](https://breakfastquay.com/rubberband/)
- **Analysis cache** — BPM results are cached per-directory so re-runs are instant
- **MP3 and FLAC** input, MP3 output

---

## Requirements

### System dependencies

```bash
brew install ffmpeg rubberband
```

### Python environment (conda recommended)

```bash
conda create -n beetroot python=3.11 -y
conda activate beetroot
pip install -r requirements.txt
```

---

## Usage

```
python beetroot.py --input <dir> --output <file.mp3> [options]
```

### Required

| Flag | Description |
|------|-------------|
| `--input DIR` | Directory containing MP3 and/or FLAC files |
| `--output FILE` | Output MP3 path |

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--shape` | `rising` | BPM arc shape: `rising`, `falling`, `sine`, or `cosine` |
| `--crossfade SECS` | `30` | Crossfade overlap in seconds (see below) |
| `--max-length MIN` | off | Cap each song at this many minutes; longer tracks fade out early |
| `--stretch` | off | Enable tempo-morphing at transitions (requires rubberband) |
| `--bpm-min BPM` | `70` | Minimum BPM after octave normalization |
| `--bpm-max BPM` | `175` | Maximum BPM after octave normalization |
| `--phase RAD` | `0.0` | Phase offset for sine/cosine curve (radians) |
| `--bitrate RATE` | `320k` | Output MP3 bitrate |
| `--no-cache` | off | Ignore and overwrite the BPM analysis cache |
| `--verbose` | off | Extra logging |

---

## BPM Shapes

The `--shape` parameter controls the energy arc of the entire mix by ordering songs along a BPM curve.

### `rising`
Songs are ordered slowest → fastest. Energy builds throughout the mix.
```
BPM  ▲
     │                    ●
     │               ●
     │          ●
     │     ●
     │●
     └──────────────────── time
```

### `falling`
Songs are ordered fastest → slowest. Energy winds down.
```
BPM  ▲
     │●
     │     ●
     │          ●
     │               ●
     │                    ●
     └──────────────────── time
```

### `sine`
Starts at mid-BPM, rises to the fastest tracks in the middle of the mix, descends to the slowest, then climbs back toward mid. A full arc.
```
BPM  ▲
     │          ●
     │     ●         ●
     │●                   ●
     │
     └──────────────────── time
```

### `cosine`
Starts at the fastest tracks, dips to the slowest in the middle, and climbs back to fast at the end. The inverse of sine.
```
BPM  ▲
     │●                   ●
     │     ●         ●
     │          ●
     │
     └──────────────────── time
```

The `--phase` flag shifts the sine/cosine curve by any radian offset, letting you start at any point in the arc.

---

## Crossfade

The `--crossfade SECS` parameter controls how long the blend between two songs lasts.

With `--crossfade 10`:

```
Song A: [body at full volume...][A fades 100%→0% over 10s    ]
Song B:                   [     B fades 0%→100% over 10s     ][body at full volume...]
                          |← 5s solo →|← 5s overlap →|← 5s solo →|
```

- **A** begins fading out 10 seconds before its end
- **B** begins fading in, and both songs are audible simultaneously for `crossfade / 2` seconds
- **B** finishes fading in `crossfade / 2` seconds after A has ended

The result is a smooth, gap-free blend where you always hear both tracks during the overlap.

---

## Max Song Length

`--max-length 3` caps every song at 3 minutes. Songs shorter than 3 minutes play in full. Songs longer than 3 minutes fade out at the 3-minute mark (snapped to the nearest detected beat) and crossfade into the next track.

---

## Example

```bash
# Sine-shaped mix, 30s crossfades, cap each song at 4 minutes
python beetroot.py \
  --input ~/Music/sets/techno \
  --output ~/Desktop/saturday_mix.mp3 \
  --shape sine \
  --crossfade 30 \
  --max-length 4

# Cosine energy arc (starts and ends energetic, dips in the middle)
python beetroot.py \
  --input ~/Music/sets/house \
  --output ~/Desktop/sunday_mix.mp3 \
  --shape cosine \
  --crossfade 60
```

---

## BPM Cache

After the first run, BPM analysis results are stored in `.beetroot_cache.json` inside your input directory. Subsequent runs skip re-analysis for unchanged files, making re-runs near-instant.

If a detected BPM sounds wrong you can edit the cache file directly — find the track's entry and change the `"bpm"` value. Use `--no-cache` to force a full re-analysis.

---

## How It Works

1. **Discover** — scans the input directory for `.mp3` and `.flac` files
2. **Analyze** — runs librosa's beat tracker on each file with three different starting BPMs (90, 120, 150) and picks the result with the highest onset-strength score; applies octave normalization to collapse half/double-time detection errors
3. **Order** — assigns songs to positions on the chosen BPM curve; for `sine`/`cosine` the assignment uses the Hungarian algorithm (`scipy.optimize.linear_sum_assignment`) to minimize total BPM deviation from the ideal curve
4. **Mix** — for each adjacent pair, cuts song A at `crossfade_sec` before its intended end (snapped to the nearest beat), fades A out over that window while fading B in over the same window, overlapping them by `crossfade / 2` seconds
5. **Export** — concatenates everything and encodes to MP3 via ffmpeg

---

## Project Structure

```
beetroot/
  beetroot.py     — CLI entry point and pipeline orchestration
  analyzer.py     — BPM detection, beat tracking, analysis cache
  orderer.py      — BPM curve ordering (rising / falling / sine / cosine)
  mixer.py        — crossfade transitions, time-stretch, export
  requirements.txt
```

---

*Built entirely by Claude Sonnet 4.6. Pure vibe coding, zero human keystrokes.*
