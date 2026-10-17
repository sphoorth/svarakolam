"""Periodic C1 cubic Hermite geometry and a shared chronological drawing timeline."""
from __future__ import annotations

import bisect
import numpy as np


def cubic(points, t):
    p = np.asarray(points, dtype=float)
    t = np.asarray(t)[..., None]
    return (1-t)**3*p[0] + 3*(1-t)**2*t*p[1] + 3*(1-t)*t*t*p[2] + t**3*p[3]


def build_geometry(plan: dict, analysis: dict) -> dict:
    anchors = plan["anchors"]
    p = np.asarray([a["point"] for a in anchors])
    count = len(p)
    notes = analysis["notes"]
    # Allocate path length to successive musical intervals, including rests. No
    # geometry is reordered after planning. Playback is reversible by time alone.
    times = sorted(set([0., analysis["duration"]] + [n["start"] for n in notes] +
                       [n["end"] for n in notes]))
    durations = np.diff(times)
    weights = []
    starts = [n["start"] for n in notes]
    for t, dt in zip(times, durations):
        note = notes[max(0, bisect.bisect_right(starts, t) - 1)] if notes else {}
        voiced = note.get("voiced", False) and t < note.get("end", 0)
        weights.append(dt * ((1 + .12 * abs(note.get("semitone", 0)) / 12 +
                                  .3 * note.get("gamaka", 0) / 100) if voiced else .35))
    progress = np.r_[0, np.cumsum(weights)]
    progress /= progress[-1]
    timeline = [{"time": float(t), "progress": float(q)} for t, q in zip(times, progress)]
    tangent = []
    for i, a in enumerate(anchors):
        delta = np.asarray(a.get("tangent", p[(i+1) % count] - p[i-1]))
        delta /= max(np.linalg.norm(delta), 1e-12)
        fraction = i / count
        music_time = float(np.interp(fraction, progress, times))
        note = notes[max(0, bisect.bisect_right(starts, music_time)-1)] if notes else {}
        modulation = min(1., float(note.get("gamaka", 0)) / 100)
        reach = min(np.linalg.norm(p[i] - p[i-1]), np.linalg.norm(p[(i+1) % count] - p[i]))
        tangent.append(delta * reach * (.24 + .07 * modulation))
    segments, lengths = [], []
    for i in range(count):
        j = (i + 1) % count
        points = [p[i], p[i]+tangent[i], p[j]-tangent[j], p[j]]
        samples = cubic(points, np.linspace(0, 1, 25))
        lut = np.r_[0, np.cumsum(np.linalg.norm(np.diff(samples, axis=0), axis=1))]
        lengths.append(float(lut[-1]))
        segments.append(dict(points=np.asarray(points).tolist(), length=float(lut[-1]),
                             lut=lut.tolist()))
    cumulative = np.r_[0, np.cumsum(lengths)]
    crossings = []
    for i, a in enumerate(anchors):
        if a["crossing"]:
            crossings.append(dict(id=a["crossing"], point=a["point"], over=a["over"],
                                  distance=float(cumulative[i]), incoming=(i-1) % count, outgoing=i))
    all_points = np.asarray([q for s in segments for q in s["points"]])
    lo, hi = all_points.min(axis=0)-.5, all_points.max(axis=0)+.5
    return dict(segments=segments, cumulative=cumulative.tolist(), length=float(cumulative[-1]),
                timeline=timeline, crossings=crossings, dots=plan["dots"],
                bounds=[float(lo[0]), float(lo[1]), float(hi[0]-lo[0]), float(hi[1]-lo[1])],
                topology={k: v for k, v in plan.items() if k not in {"anchors", "dots"}})


def progress_at(geometry: dict, time: float) -> float:
    timeline = geometry["timeline"]
    return float(np.interp(time, [v["time"] for v in timeline], [v["progress"] for v in timeline]))


def partial_curve(points, t: float):
    """Exact de Casteljau prefix, shared by SVG-compatible renderers."""
    a, b, c, d = np.asarray(points)
    ab, bc, cd = a+(b-a)*t, b+(c-b)*t, c+(d-c)*t
    abc, bcd = ab+(bc-ab)*t, bc+(cd-bc)*t
    return np.asarray([a, ab, abc, abc+(bcd-abc)*t])


def visible_curves(geometry: dict, progress: float):
    distance = np.clip(progress, 0, 1) * geometry["length"]
    for i, segment in enumerate(geometry["segments"]):
        available = distance - geometry["cumulative"][i]
        if available <= 0:
            break
        if available >= segment["length"]:
            yield segment["points"]
        else:
            t = np.interp(available, segment["lut"], np.linspace(0, 1, len(segment["lut"])))
            yield partial_curve(segment["points"], float(t)).tolist()
            break
