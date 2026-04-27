import json
import shutil
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import librosa
import numpy as np


@dataclass
class TrackInfo:
    path: Path
    bpm: float
    beat_times: np.ndarray
    duration_sec: float
    sample_rate: int = 44100
    rms_energy: np.ndarray = field(default_factory=lambda: np.array([]))

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "bpm": self.bpm,
            "beat_times": self.beat_times.tolist(),
            "duration_sec": self.duration_sec,
            "sample_rate": self.sample_rate,
            "rms_energy": [round(float(v), 6) for v in self.rms_energy],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TrackInfo":
        return cls(
            path=Path(d["path"]),
            bpm=d["bpm"],
            beat_times=np.array(d["beat_times"]),
            duration_sec=d["duration_sec"],
            sample_rate=d.get("sample_rate", 44100),
            rms_energy=np.array(d.get("rms_energy", [])),
        )


CACHE_FILENAME = ".beetroot_cache.json"
AUDIO_EXTENSIONS = {".mp3", ".flac"}


def _check_dependencies() -> None:
    if not shutil.which("ffmpeg"):
        print("Error: ffmpeg not found on PATH. Install with: brew install ffmpeg", file=sys.stderr)
        sys.exit(1)


def discover_tracks(input_dir: Path) -> list[Path]:
    tracks = sorted(
        p for p in input_dir.iterdir()
        if p.suffix.lower() in AUDIO_EXTENSIONS
    )
    return tracks


def load_cache(input_dir: Path) -> dict:
    cache_path = input_dir / CACHE_FILENAME
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_cache(input_dir: Path, cache: dict) -> None:
    cache_path = input_dir / CACHE_FILENAME
    cache_path.write_text(json.dumps(cache, indent=2))


def _normalize_bpm(bpm: float, bpm_min: float, bpm_max: float) -> float:
    while bpm < bpm_min and bpm > 0:
        bpm *= 2.0
    while bpm > bpm_max:
        bpm /= 2.0
    return bpm


def _best_beat_track(y: np.ndarray, sr: int) -> tuple[float, np.ndarray]:
    onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=512)
    best_bpm = 120.0
    best_beat_times = np.array([])
    best_score = -1.0

    for start_bpm in [90, 120, 150]:
        tempo, beat_frames = librosa.beat.beat_track(
            onset_envelope=onset_env, sr=sr, hop_length=512, start_bpm=start_bpm
        )
        bpm = float(np.atleast_1d(tempo)[0])
        if len(beat_frames) == 0:
            continue
        score = float(np.sum(onset_env[beat_frames]))
        if score > best_score:
            best_score = score
            best_bpm = bpm
            best_beat_times = librosa.frames_to_time(beat_frames, sr=sr, hop_length=512)

    return best_bpm, best_beat_times


def analyze_track(
    path: Path,
    bpm_min: float = 70.0,
    bpm_max: float = 175.0,
    verbose: bool = False,
) -> TrackInfo:
    if verbose:
        print(f"  Analyzing: {path.name}")

    fmt = path.suffix.lower().lstrip(".")
    y, sr = librosa.load(str(path), sr=44100, mono=True)
    duration = float(len(y)) / sr

    raw_bpm, beat_times = _best_beat_track(y, sr)
    bpm = _normalize_bpm(raw_bpm, bpm_min, bpm_max)
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]

    if verbose and abs(raw_bpm - bpm) > 1.0:
        print(f"    BPM normalized: {raw_bpm:.1f} -> {bpm:.1f}")

    return TrackInfo(
        path=path,
        bpm=bpm,
        beat_times=beat_times,
        duration_sec=duration,
        sample_rate=sr,
        rms_energy=rms,
    )


def analyze_all(
    paths: list[Path],
    bpm_min: float = 70.0,
    bpm_max: float = 175.0,
    use_cache: bool = True,
    input_dir: Path | None = None,
    verbose: bool = False,
) -> list[TrackInfo]:
    _check_dependencies()

    cache: dict = {}
    if use_cache and input_dir is not None:
        cache = load_cache(input_dir)

    results: list[TrackInfo] = []

    for path in paths:
        abs_path = str(path.resolve())
        mtime = path.stat().st_mtime
        cached = cache.get(abs_path)

        if use_cache and cached and abs(cached.get("mtime", 0) - mtime) < 1.0:
            if verbose:
                print(f"  Cache hit: {path.name} ({cached['bpm']:.1f} BPM)")
            results.append(TrackInfo.from_dict(cached))
            continue

        info = analyze_track(path, bpm_min=bpm_min, bpm_max=bpm_max, verbose=verbose)
        print(f"  {path.name}: {info.bpm:.1f} BPM")

        entry = info.to_dict()
        entry["mtime"] = mtime
        cache[abs_path] = entry
        results.append(info)

    if use_cache and input_dir is not None:
        save_cache(input_dir, cache)

    return results
