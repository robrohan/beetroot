#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

from analyzer import analyze_all, discover_tracks
from mixer import build_mix, export_mix
from orderer import order_tracks


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="beetroot: auto-DJ that beat-analyzes music and creates a BPM-shaped mix"
    )
    p.add_argument("--input", "-i", required=True, type=Path, metavar="DIR",
                   help="Directory containing MP3/FLAC files")
    p.add_argument("--output", "-o", required=True, type=Path, metavar="FILE",
                   help="Output MP3 file path")
    p.add_argument("--shape", "-s", default="rising",
                   choices=["rising", "falling", "sine", "cosine"],
                   help="BPM arc shape: rising, falling, or sine (default: rising)")
    p.add_argument("--crossfade", type=float, default=30.0, metavar="SECS",
                   help="Crossfade overlap between songs in seconds (default: 30)")
    p.add_argument("--stretch", action="store_true",
                   help="Enable time-stretch transitions (requires rubberband)")
    p.add_argument("--bpm-min", type=float, default=70.0, metavar="BPM",
                   help="Minimum BPM after octave normalization (default: 70)")
    p.add_argument("--bpm-max", type=float, default=175.0, metavar="BPM",
                   help="Maximum BPM after octave normalization (default: 175)")
    p.add_argument("--phase", type=float, default=0.0, metavar="RAD",
                   help="Sine phase offset in radians (default: 0.0)")
    p.add_argument("--bitrate", default="320k", metavar="RATE",
                   help="Output MP3 bitrate (default: 320k)")
    p.add_argument("--max-length", type=float, default=None, metavar="MIN",
                   help="Max song length in minutes; longer songs fade out at this point")
    p.add_argument("--no-cache", action="store_true",
                   help="Ignore and overwrite the BPM analysis cache")
    p.add_argument("--verbose", "-v", action="store_true",
                   help="Extra logging")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if not args.input.is_dir():
        print(f"Error: {args.input} is not a directory.", file=sys.stderr)
        sys.exit(1)

    max_length_sec = args.max_length * 60.0 if args.max_length is not None else None
    length_str = f"{args.max_length}min" if args.max_length else "full"
    print(f"beetroot | shape={args.shape} | crossfade={args.crossfade}s | stretch={args.stretch} | max-length={length_str}")
    print(f"Input:  {args.input}")
    print(f"Output: {args.output}")

    # 1. Discover
    tracks = discover_tracks(args.input)
    if not tracks:
        print(f"Error: no MP3 or FLAC files found in {args.input}", file=sys.stderr)
        sys.exit(1)
    print(f"\nFound {len(tracks)} track(s). Analyzing BPMs...")

    # 2. Analyze
    track_infos = analyze_all(
        tracks,
        bpm_min=args.bpm_min,
        bpm_max=args.bpm_max,
        use_cache=not args.no_cache,
        input_dir=args.input,
        verbose=args.verbose,
    )

    # 3. Order
    ordered = order_tracks(track_infos, shape=args.shape, phase=args.phase)
    print(f"\nTrack order ({args.shape}):")
    for i, t in enumerate(ordered, 1):
        print(f"  {i:2d}. {t.path.name:50s}  {t.bpm:6.1f} BPM")

    # 4. Mix
    mix = build_mix(
        ordered,
        crossfade_sec=args.crossfade,
        use_stretch=args.stretch,
        max_length_sec=max_length_sec,
        verbose=args.verbose,
    )

    # 5. Export
    export_mix(mix, args.output, bitrate=args.bitrate)


if __name__ == "__main__":
    main()
