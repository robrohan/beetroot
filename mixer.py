import sys
import shutil
from pathlib import Path

import numpy as np
import pyrubberband as pyrb
from pydub import AudioSegment

from analyzer import TrackInfo


def load_segment(track: TrackInfo) -> AudioSegment:
    fmt = track.path.suffix.lower().lstrip(".")
    seg = AudioSegment.from_file(str(track.path), format=fmt)
    return seg.set_frame_rate(44100).set_channels(2).set_sample_width(2)


def find_beat_aligned_cut(
    beat_times: np.ndarray,
    duration_sec: float,
    bars: int = 4,
    time_sig: int = 4,
    fallback_ratio: float = 0.85,
) -> float:
    beats_needed = bars * time_sig
    if len(beat_times) < beats_needed + 1:
        return duration_sec * fallback_ratio

    # Walk backwards to find a beat that is at least `beats_needed` beats from the end
    target_idx = len(beat_times) - beats_needed - 1
    return float(beat_times[max(0, target_idx)])


def find_beat_nearest(beat_times: np.ndarray, target_sec: float) -> float:
    if len(beat_times) == 0:
        return target_sec
    idx = int(np.argmin(np.abs(beat_times - target_sec)))
    return float(beat_times[idx])


def find_beat_aligned_entry(beat_times: np.ndarray) -> float:
    if len(beat_times) == 0:
        return 0.0
    return float(beat_times[0])


def audiosegment_to_numpy(seg: AudioSegment) -> tuple[np.ndarray, int]:
    samples = np.array(seg.get_array_of_samples(), dtype=np.float32)
    samples /= 32768.0
    # reshape to (channels, samples) for pyrubberband
    channels = seg.channels
    samples = samples.reshape((-1, channels)).T  # (channels, n_samples)
    return samples, seg.frame_rate


def numpy_to_audiosegment(y: np.ndarray, sr: int) -> AudioSegment:
    # y is (channels, n_samples); convert to interleaved int16
    clipped = np.clip(y, -1.0, 1.0)
    interleaved = (clipped.T * 32767.0).astype(np.int16)  # (n_samples, channels)
    raw = interleaved.tobytes()
    channels = y.shape[0]
    return AudioSegment(
        data=raw,
        sample_width=2,
        frame_rate=sr,
        channels=channels,
    )


def stretch_tail(seg: AudioSegment, from_bpm: float, to_bpm: float) -> AudioSegment:
    ratio = from_bpm / to_bpm
    y, sr = audiosegment_to_numpy(seg)
    # pyrubberband time_stretch: ratio > 1 = slower, ratio < 1 = faster
    stretched = pyrb.time_stretch(y, sr, ratio)
    return numpy_to_audiosegment(stretched, sr)


def build_mix(
    ordered_tracks: list[TrackInfo],
    crossfade_sec: float = 30.0,
    use_stretch: bool = False,
    bpm_ratio_threshold: float = 0.25,
    max_length_sec: float | None = None,
    verbose: bool = False,
) -> AudioSegment:
    if not ordered_tracks:
        raise ValueError("No tracks to mix.")

    n = len(ordered_tracks)
    print(f"\nBuilding mix from {n} tracks...")

    crossfade_ms = int(crossfade_sec * 1000)

    if n == 1:
        track = ordered_tracks[0]
        seg = load_segment(track)
        if max_length_sec and track.duration_sec > max_length_sec:
            seg = seg[:int(find_beat_nearest(track.beat_times, max_length_sec) * 1000)]
        return seg

    result = AudioSegment.empty()
    seg_a = load_segment(ordered_tracks[0])
    seg_a_start_ms = 0

    for i in range(n - 1):
        track_a = ordered_tracks[i]
        track_b = ordered_tracks[i + 1]

        if verbose:
            print(f"  [{i+1}/{n}] {track_a.path.name} ({track_a.bpm:.1f} BPM)")
        else:
            print(f"  Mixing: {track_a.path.name} -> {track_b.path.name}")

        seg_b = load_segment(track_b)

        # Intended end of A (max_length cap or natural end)
        if max_length_sec and track_a.duration_sec > max_length_sec:
            intended_end_sec = max_length_sec
        else:
            intended_end_sec = track_a.duration_sec
        intended_end_ms = min(int(intended_end_sec * 1000), len(seg_a))

        # Cut A exactly crossfade_sec before its intended end, snapped to nearest beat
        cut_target_sec = max(0.0, intended_end_sec - crossfade_sec)
        cut_sec = find_beat_nearest(track_a.beat_times, cut_target_sec)
        cut_ms = int(cut_sec * 1000)

        # Entry into B (first detected beat, skips any silent intro)
        entry_b_ms = int(find_beat_aligned_entry(track_b.beat_times) * 1000)

        body_a = seg_a[seg_a_start_ms:cut_ms]
        # tail_a: A's fade-out zone (crossfade_sec long, or shorter if song is short)
        tail_a = seg_a[cut_ms:intended_end_ms]
        # head_b: B's fade-in zone, same duration as tail_a
        head_b = seg_b[entry_b_ms : entry_b_ms + len(tail_a)]

        if use_stretch:
            ratio = track_a.bpm / track_b.bpm
            if abs(ratio - 1.0) <= bpm_ratio_threshold:
                try:
                    tail_a = stretch_tail(tail_a, track_a.bpm, track_b.bpm)
                except Exception as e:
                    print(f"  Warning: time-stretch failed ({e}), using plain crossfade.", file=sys.stderr)
            else:
                print(
                    f"  Warning: BPM ratio {ratio:.2f} exceeds threshold; skipping stretch.",
                    file=sys.stderr,
                )

        # A fades out over its full tail, B fades in over its full head.
        # They overlap by half the crossfade duration so both are audible throughout.
        actual_cf = min(len(tail_a), len(head_b))
        overlap_ms = actual_cf // 2

        if actual_cf > 0:
            tail_a_faded = tail_a.fade_out(actual_cf)
            head_b_faded = head_b.fade_in(actual_cf)

            # Split into: [A solo fade] [A+B overlap] [B solo fade]
            solo_a = tail_a_faded[: actual_cf - overlap_ms]
            a_in_overlap = tail_a_faded[actual_cf - overlap_ms :]
            b_in_overlap = head_b_faded[:overlap_ms]
            solo_b = head_b_faded[overlap_ms:]

            overlap_zone = a_in_overlap.overlay(b_in_overlap)
            transition = solo_a + overlap_zone + solo_b
        else:
            transition = head_b

        result = result + body_a + transition

        # B continues from after its fade-in head
        seg_a = seg_b
        seg_a_start_ms = entry_b_ms + actual_cf

    # Append the remainder of the last track
    last_track = ordered_tracks[-1]
    if verbose:
        print(f"  [{n}/{n}] {last_track.path.name} ({last_track.bpm:.1f} BPM)")

    last_end_ms = len(seg_a)
    if max_length_sec and last_track.duration_sec > max_length_sec:
        last_end_ms = min(last_end_ms, int(find_beat_nearest(last_track.beat_times, max_length_sec) * 1000))

    result = result + seg_a[seg_a_start_ms:last_end_ms]
    return result


def export_mix(mix: AudioSegment, output_path: Path, bitrate: str = "320k") -> None:
    print(f"\nExporting to {output_path} at {bitrate}...")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    mix.export(str(output_path), format="mp3", bitrate=bitrate)
    duration_min = len(mix) / 60000
    print(f"Done. Mix duration: {duration_min:.1f} minutes ({len(mix) / 1000:.0f} seconds)")
