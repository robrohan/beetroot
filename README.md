```
  ██████╗ ███████╗███████╗████████╗██████╗  ██████╗  ██████╗ ████████╗
  ██╔══██╗██╔════╝██╔════╝╚══██╔══╝██╔══██╗██╔═══██╗██╔═══██╗╚══██╔══╝
  ██████╔╝█████╗  █████╗     ██║   ██████╔╝██║   ██║██║   ██║   ██║
  ██╔══██╗██╔══╝  ██╔══╝     ██║   ██╔══██╗██║   ██║██║   ██║   ██║
  ██████╔╝███████╗███████╗   ██║   ██║  ██║╚██████╔╝╚██████╔╝   ██║
  ╚═════╝ ╚══════╝╚══════╝   ╚═╝   ╚═╝  ╚═╝ ╚═════╝  ╚═════╝   ╚═╝

                  ,-.
               ___/ |
          .-'`  |   |     auto-DJ · BPM analysis · beat-matched mixing
         /  |   |   |
        /  /|   '---'
       |  / |   /
       | /  '--'
       '/
```

> **Fully vibe coded by [Claude Sonnet 4.6](https://anthropic.com) (Anthropic). Every line of Python in this project was written by an AI — no human code was harmed in the making of this mix.**

beetroot is a command-line auto-DJ that analyzes a folder of music files, detects the BPM of every track, orders them along a BPM curve of your choosing, and stitches them into a single seamless MP3 with smooth crossfade transitions.

---

## Features

- **BPM detection** — uses [librosa](https://librosa.org/) with a multi-pass beat tracker and octave normalization to reliably detect tempo across genres
- **BPM curve shaping** — four modes for controlling how the energy arc of your mix evolves over time
- **Three mixing styles** — equal-power, DJ EQ bass-swap, or random per transition
- **Energy-based cue detection** — finds the natural quiet moment (breakdown, outro) in each track using RMS energy analysis
- **Smooth crossfades** — independent fade-out and fade-in with configurable overlap so you always hear both songs during the transition
- **Max song length cap** — trim long tracks and fade into the next one at a set duration
- **Per-track RMS normalization** + final peak normalization so every song sits at the same perceived loudness
- **Optional time-stretch transitions** — tempo-morph between songs at BPM boundaries using [librosa](https://librosa.org/)'s phase vocoder
- **Analysis cache** — BPM and RMS results are cached per-directory so re-runs are instant
- **MP3 and FLAC** input, MP3 output

---

## Requirements

### System dependencies

```bash
brew install ffmpeg
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
| `--transition-style` | `power` | Mixing style: `linear`, `power`, `eq`, or `random` |
| `--max-length MIN` | off | Cap each song at this many minutes; longer tracks fade out early |
| `--no-energy-cue` | off | Use fixed time offset for cut points instead of RMS energy detection |
| `--stretch` | off | Enable tempo-morphing at transitions |
| `--bpm-min BPM` | `70` | Minimum BPM after octave normalization |
| `--bpm-max BPM` | `175` | Maximum BPM after octave normalization |
| `--phase RAD` | `0.0` | Phase offset for sine/cosine curve (radians) |
| `--bitrate RATE` | `320k` | Output MP3 bitrate |
| `--no-normalize` | off | Skip per-track and final normalization |
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

## Transition Styles

The `--transition-style` parameter controls how each pair of songs is blended together.

### `power` (default)
Equal-power crossfade using cosine/sine gain envelopes. Maintains constant perceived loudness throughout the transition — no volume dip in the middle.

```
A: ████████████████▓▓▓▒▒▒░░░
B:             ░░░▒▒▒▓▓▓████████████████
               └── overlap ──┘
```

### `eq`
DJ-style EQ crossfade. The treble (above 300 Hz) fades linearly across the full crossfade window. The bass swaps hard at the midpoint — A's kick/bass cuts out while B's drops in. Sounds like a real DJ mix.

```
Treble: A ████████░░░░░░░  B ░░░░░░░████████
Bass:   A ████████          B         ████████
               └── midpoint ──┘
```

### `eq` — when to use it
Works best when adjacent songs have similar bass lines (the hard swap is less noticeable). Great for electronic, hip-hop, and dance music.

### `random`
Picks `power` or `eq` independently at random for each transition. Creates variety in the mix and sounds more organic.

---

## Crossfade

The `--crossfade SECS` parameter controls how long the blend between two songs lasts.

With `--crossfade 10`:

```
Song A: [body at full volume...][A fades 100%→0% over 10s    ]
Song B:                   [     B fades 0%→100% over 10s     ][body...]
                          |← 5s solo →|← 5s overlap →|← 5s solo →|
```

- **A** begins fading out 10 seconds before its end
- **B** begins fading in, and both songs are audible simultaneously for `crossfade / 2` seconds
- **B** finishes fading in `crossfade / 2` seconds after A has ended

---

## Energy Cue Detection

By default beetroot uses RMS energy analysis to find the natural transition point in each track — the quietest moment (typically a breakdown or outro) within the window `[end - 2×crossfade, end - 0.25×crossfade]`. This makes transitions happen at musically natural moments rather than a rigid fixed offset.

Use `--no-energy-cue` to revert to a simple `end - crossfade_sec` cut point.

---

## Max Song Length

`--max-length 3` caps every song at 3 minutes. Songs shorter than 3 minutes play in full. Songs longer than 3 minutes fade out at the 3-minute mark (snapped to the nearest detected beat) and crossfade into the next track.

---

## Normalization

Each track is normalized to −20 dBFS RMS before mixing so songs mastered at different levels don't cause jarring volume jumps. After the full mix is assembled, a final peak normalization brings the output to −0.1 dBFS.

Use `--no-normalize` to skip both steps (e.g. if you've pre-levelled the tracks yourself).

---

## Examples

```bash
# Default: rising BPM arc, equal-power fades, 30s crossfade
python beetroot.py --input ~/Music/sets/techno --output ~/Desktop/mix.mp3

# Sine-shaped arc, DJ EQ transitions, cap songs at 4 minutes
python beetroot.py \
  --input ~/Music/sets/house \
  --output ~/Desktop/saturday.mp3 \
  --shape sine \
  --transition-style eq \
  --crossfade 30 \
  --max-length 4

# Cosine arc (starts and ends energetic), random transitions, 60s blends
python beetroot.py \
  --input ~/Music/sets/mixed \
  --output ~/Desktop/sunday.mp3 \
  --shape cosine \
  --transition-style random \
  --crossfade 60
```

---

## BPM Cache

After the first run, BPM and RMS energy analysis results are stored in `.beetroot_cache.json` inside your input directory. Subsequent runs skip re-analysis for unchanged files, making re-runs near-instant.

If a detected BPM sounds wrong you can edit the cache file directly — find the track's entry and change the `"bpm"` value. Use `--no-cache` to force a full re-analysis.

---

## How It Works

1. **Discover** — scans the input directory for `.mp3` and `.flac` files
2. **Analyze** — runs librosa's beat tracker on each file with three different starting BPMs (90, 120, 150) and picks the result with the highest onset-strength score; applies octave normalization to collapse half/double-time detection errors; computes RMS energy envelope
3. **Order** — assigns songs to positions on the chosen BPM curve; for `sine`/`cosine` the assignment uses the Hungarian algorithm (`scipy.optimize.linear_sum_assignment`) to minimize total BPM deviation from the ideal curve
4. **Mix** — for each adjacent pair, uses RMS energy to find the natural quiet point near the end of the outgoing track, then blends using the chosen transition style
5. **Normalize** — per-track RMS normalization before mixing, peak normalization on the final output
6. **Export** — concatenates everything and encodes to MP3 via ffmpeg

---

## Project Structure

```
beetroot/
  beetroot.py     — CLI entry point and pipeline orchestration
  analyzer.py     — BPM detection, RMS energy, beat tracking, analysis cache
  orderer.py      — BPM curve ordering (rising / falling / sine / cosine)
  mixer.py        — crossfade transitions, EQ mixing, time-stretch, export
  requirements.txt
```

---

*Built entirely by Claude Sonnet 4.6. Pure vibe coding, zero human keystrokes.*
