import random as _random
import sys
import shutil
from pathlib import Path

import librosa
import numpy as np
from pydub import AudioSegment

from analyzer import TrackInfo


def normalize_segment(seg: AudioSegment, target_dBFS: float = -20.0) -> AudioSegment:
    if seg.dBFS == float("-inf"):
        return seg
    return seg.apply_gain(target_dBFS - seg.dBFS)


def load_segment(track: TrackInfo, normalize: bool = True, target_dBFS: float = -20.0) -> AudioSegment:
    fmt = track.path.suffix.lower().lstrip(".")
    seg = AudioSegment.from_file(str(track.path), format=fmt)
    seg = seg.set_frame_rate(44100).set_channels(2).set_sample_width(2)
    if normalize:
        seg = normalize_segment(seg, target_dBFS)
    return seg


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
    # librosa rate > 1 = faster, < 1 = slower; invert from/to to get the same semantics
    rate = to_bpm / from_bpm
    y, sr = audiosegment_to_numpy(seg)
    stretched_channels = [librosa.effects.time_stretch(y[ch], rate=rate) for ch in range(y.shape[0])]
    stretched = np.stack(stretched_channels)
    return numpy_to_audiosegment(stretched, sr)


def _silent_like(duration_ms: int, ref: AudioSegment) -> AudioSegment:
    return AudioSegment.silent(duration=duration_ms, frame_rate=ref.frame_rate) \
        .set_channels(ref.channels).set_sample_width(ref.sample_width)


def _crossfade_linear(tail_a: AudioSegment, head_b: AudioSegment) -> AudioSegment:
    """Current behaviour extracted as a named function."""
    actual_cf = min(len(tail_a), len(head_b))
    if actual_cf == 0:
        return head_b
    overlap_ms = actual_cf // 2
    tail_a = tail_a[:actual_cf]
    head_b = head_b[:actual_cf]
    ta = tail_a.fade_out(actual_cf)
    hb = head_b.fade_in(actual_cf)
    solo_a = ta[:actual_cf - overlap_ms]
    overlap = ta[actual_cf - overlap_ms:].overlay(hb[:overlap_ms])
    solo_b = hb[overlap_ms:]
    return solo_a + overlap + solo_b


def _crossfade_power(tail_a: AudioSegment, head_b: AudioSegment) -> AudioSegment:
    """Equal-power (cos/sin) crossfade — maintains constant perceived loudness."""
    actual_cf = min(len(tail_a), len(head_b))
    if actual_cf == 0:
        return head_b
    overlap_ms = actual_cf // 2
    tail_a = tail_a[:actual_cf]
    head_b = head_b[:actual_cf]

    y_a, sr = audiosegment_to_numpy(tail_a)
    t_a = np.linspace(0.0, np.pi / 2, y_a.shape[1])
    y_a *= np.cos(t_a)          # amplitude envelope: 1 → 0
    ta = numpy_to_audiosegment(y_a, sr)

    y_b, sr = audiosegment_to_numpy(head_b)
    t_b = np.linspace(0.0, np.pi / 2, y_b.shape[1])
    y_b *= np.sin(t_b)          # amplitude envelope: 0 → 1
    hb = numpy_to_audiosegment(y_b, sr)

    solo_a = ta[:actual_cf - overlap_ms]
    overlap = ta[actual_cf - overlap_ms:].overlay(hb[:overlap_ms])
    solo_b = hb[overlap_ms:]
    return solo_a + overlap + solo_b


def _crossfade_eq(tail_a: AudioSegment, head_b: AudioSegment) -> AudioSegment:
    """DJ EQ crossfade: treble fades linearly, bass swaps hard at the midpoint."""
    from pydub.scipy_effects import high_pass_filter, low_pass_filter

    actual_cf = min(len(tail_a), len(head_b))
    if actual_cf == 0:
        return head_b
    mid = actual_cf // 2
    tail_a = tail_a[:actual_cf]
    head_b = head_b[:actual_cf]

    BASS_HZ = 300

    a_treble = high_pass_filter(tail_a, BASS_HZ).fade_out(actual_cf)
    b_treble = high_pass_filter(head_b, BASS_HZ).fade_in(actual_cf)

    # Bass: A plays first half, B plays second half — hard swap at midpoint
    a_bass = low_pass_filter(tail_a, BASS_HZ)[:mid] + _silent_like(actual_cf - mid, tail_a)
    b_bass = _silent_like(mid, head_b) + low_pass_filter(head_b, BASS_HZ)[mid:actual_cf]

    return a_treble.overlay(b_treble).overlay(a_bass).overlay(b_bass)


def find_energy_cue_point(
    track: TrackInfo,
    intended_end_sec: float,
    crossfade_sec: float,
) -> float:
    """Return the lowest-energy beat in the search window near the end of the track."""
    if len(track.rms_energy) == 0:
        return max(0.0, intended_end_sec - crossfade_sec)

    frames_per_sec = track.sample_rate / 512.0
    start_sec = max(0.0, intended_end_sec - crossfade_sec * 2)
    end_sec = max(0.0, intended_end_sec - crossfade_sec * 0.25)

    start_f = int(start_sec * frames_per_sec)
    end_f = min(int(end_sec * frames_per_sec), len(track.rms_energy) - 1)

    if start_f >= end_f:
        return max(0.0, intended_end_sec - crossfade_sec)

    min_sec = (start_f + int(np.argmin(track.rms_energy[start_f:end_f]))) / frames_per_sec
    return find_beat_nearest(track.beat_times, min_sec)


def build_mix(
    ordered_tracks: list[TrackInfo],
    crossfade_sec: float = 30.0,
    use_stretch: bool = False,
    bpm_ratio_threshold: float = 0.25,
    max_length_sec: float | None = None,
    normalize: bool = True,
    normalize_target_dBFS: float = -20.0,
    transition_style: str = "power",
    energy_cue: bool = True,
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
    seg_a = load_segment(ordered_tracks[0], normalize=normalize, target_dBFS=normalize_target_dBFS)
    seg_a_start_ms = 0

    for i in range(n - 1):
        track_a = ordered_tracks[i]
        track_b = ordered_tracks[i + 1]

        if verbose:
            print(f"  [{i+1}/{n}] {track_a.path.name} ({track_a.bpm:.1f} BPM)")
        else:
            print(f"  Mixing: {track_a.path.name} -> {track_b.path.name}")

        seg_b = load_segment(track_b, normalize=normalize, target_dBFS=normalize_target_dBFS)

        # Intended end of A (max_length cap or natural end)
        if max_length_sec and track_a.duration_sec > max_length_sec:
            intended_end_sec = max_length_sec
        else:
            intended_end_sec = track_a.duration_sec
        intended_end_ms = min(int(intended_end_sec * 1000), len(seg_a))

        # Find cut point: energy-based (natural quiet moment) or fixed offset
        if energy_cue:
            cut_sec = find_energy_cue_point(track_a, intended_end_sec, crossfade_sec)
        else:
            cut_sec = find_beat_nearest(track_a.beat_times, max(0.0, intended_end_sec - crossfade_sec))
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

        # actual_cf is how much of B's head was consumed — needed to set the start offset
        actual_cf = min(len(tail_a), len(head_b))

        # Pick transition style (random chooses per-pair)
        style = transition_style if transition_style != "random" else _random.choice(["power", "eq"])
        if verbose:
            print(f"    transition style: {style}")

        if style == "power":
            transition = _crossfade_power(tail_a, head_b)
        elif style == "eq":
            transition = _crossfade_eq(tail_a, head_b)
        else:
            transition = _crossfade_linear(tail_a, head_b)

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

    if normalize:
        print("  Normalizing final mix...")
        result = result.normalize(headroom=0.1)

    return result


def export_mix(mix: AudioSegment, output_path: Path, bitrate: str = "320k") -> None:
    print(f"\nExporting to {output_path} at {bitrate}...")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    mix.export(str(output_path), format="mp3", bitrate=bitrate)
    duration_min = len(mix) / 60000
    print(f"Done. Mix duration: {duration_min:.1f} minutes ({len(mix) / 1000:.0f} seconds)")
