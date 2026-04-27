import numpy as np
from scipy.optimize import linear_sum_assignment

from analyzer import TrackInfo


def order_tracks(
    tracks: list[TrackInfo],
    shape: str,
    phase: float = 0.0,
) -> list[TrackInfo]:
    if len(tracks) <= 1:
        return list(tracks)

    if shape == "rising":
        return _order_rising(tracks)
    elif shape == "falling":
        return _order_falling(tracks)
    elif shape == "sine":
        return _order_sine(tracks, phase)
    elif shape == "cosine":
        return _order_sine(tracks, phase + np.pi / 2)
    else:
        raise ValueError(f"Unknown shape: {shape!r}. Use rising, falling, sine, or cosine.")


def _order_rising(tracks: list[TrackInfo]) -> list[TrackInfo]:
    return sorted(tracks, key=lambda t: t.bpm)


def _order_falling(tracks: list[TrackInfo]) -> list[TrackInfo]:
    return sorted(tracks, key=lambda t: t.bpm, reverse=True)


def _order_sine(tracks: list[TrackInfo], phase: float = 0.0) -> list[TrackInfo]:
    bpms = [t.bpm for t in tracks]
    targets = _generate_sine_targets(bpms, len(tracks), phase)
    return _hungarian_assign(tracks, targets)


def _generate_sine_targets(bpms: list[float], n: int, phase: float) -> np.ndarray:
    min_bpm = min(bpms)
    max_bpm = max(bpms)
    mean_bpm = (min_bpm + max_bpm) / 2.0
    amplitude = (max_bpm - min_bpm) / 2.0

    i = np.arange(n)
    # phase=0: starts at mean, rises to max at N/4, mean at N/2, min at 3N/4, back to mean
    targets = mean_bpm + amplitude * np.sin(2 * np.pi * i / n + phase)
    return targets


def _hungarian_assign(songs: list[TrackInfo], targets: np.ndarray) -> list[TrackInfo]:
    n = len(songs)
    cost = np.zeros((n, n))
    for i, song in enumerate(songs):
        for j, target in enumerate(targets):
            cost[i][j] = abs(song.bpm - target)

    row_ind, col_ind = linear_sum_assignment(cost)
    # col_ind[i] is the position assigned to song i
    # We want songs sorted by their assigned position
    assigned = [None] * n
    for song_idx, pos_idx in zip(row_ind, col_ind):
        assigned[pos_idx] = songs[song_idx]

    return assigned
