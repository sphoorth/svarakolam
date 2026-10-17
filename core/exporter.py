"""Vector export and bounded-memory H.264/AAC rendering of the shared timeline."""
from __future__ import annotations

import bisect
import math
from pathlib import Path

import imageio.v2 as imageio
import numpy as np
import svgwrite
from PIL import Image, ImageDraw, ImageFont

from .bezier_geometry import cubic, partial_curve, progress_at, visible_curves

BACKGROUND = "#202c2b"
CHALK = "#f6ead1"
GOLD = "#d7a75b"
STROKE = .038


def path_data(curves, close=False):
    parts = []
    for i, points in enumerate(curves):
        if i == 0:
            parts.append(f"M {points[0][0]:.8f},{points[0][1]:.8f}")
        parts.append("C " + " ".join(f"{p[0]:.8f},{p[1]:.8f}" for p in points[1:]))
    if close:
        parts.append("Z")
    return " ".join(parts)


def weave_bridges(geometry, progress):
    """Paint bridges only once BOTH fixed-pairing strands have arrived.

    These are cosmetic overlays. The primary SVG path remains a single closed,
    continuous curve; visual underpasses never delete geometry.
    """
    distance = progress * geometry["length"]
    for cross in geometry["crossings"]:
        if not cross["over"] or distance < cross["distance"]:
            continue
        other = next(c for c in geometry["crossings"] if c["id"] == cross["id"] and not c["over"])
        if distance < other["distance"]:
            continue
        incoming = geometry["segments"][cross["incoming"]]["points"]
        # Reversing a prefix extracts a cubic tail exactly.
        tail = partial_curve(incoming[::-1], .22)[::-1].tolist()
        outgoing = geometry["segments"][cross["outgoing"]]
        available = min(outgoing["length"], distance-cross["distance"])
        t = float(np.interp(available, outgoing["lut"], np.linspace(0, 1, len(outgoing["lut"]))))
        yield [tail, partial_curve(outgoing["points"], min(.22, t)).tolist()]


def export_svg(geometry: dict, destination: Path):
    bounds = geometry["bounds"]
    drawing = svgwrite.Drawing(str(destination), size=("100%", "100%"),
                               viewBox=" ".join(map(str, bounds)))
    drawing.set_desc(title="SvaraKolam · Single-line Sikku Kolam",
                     desc="One closed C1-continuous cubic path. Bridge overlays depict over/under crossings.")
    drawing.add(drawing.rect(insert=bounds[:2], size=bounds[2:], fill=BACKGROUND))
    for point in geometry["dots"]:
        drawing.add(drawing.circle(center=point, r=.047, fill=GOLD))
    curves = [s["points"] for s in geometry["segments"]]
    drawing.add(drawing.path(d=path_data(curves, close=True), id="single-closed-circuit",
                             fill="none", stroke=CHALK, stroke_width=STROKE,
                             stroke_linecap="round", stroke_linejoin="round"))
    for bridge in weave_bridges(geometry, 1):
        for color, width in [(BACKGROUND, STROKE*3.2), (CHALK, STROKE)]:
            drawing.add(drawing.path(d=path_data(bridge), fill="none", stroke=color,
                                     stroke_width=width, stroke_linecap="round"))
    drawing.save()


def active_hud(analysis: dict, t: float):
    notes = analysis["notes"]
    i = max(0, bisect.bisect_right([n["start"] for n in notes], t)-1)
    note = notes[i] if notes else {"swara": "—", "gamaka": 0}
    beat = bisect.bisect_right(analysis["beats"], t)-1
    return note, (beat % analysis["tala"] + 1) if beat >= 0 else 0


def export_mp4(geometry: dict, analysis: dict, audio_path: Path, destination: Path,
               report=lambda *_: None, fps=30, size=960):
    x, y, w, h = geometry["bounds"]
    scale = (size-100)/max(w, h)
    offset = np.array([(size-w*scale)/2-x*scale, 100+(size-h*scale)/2-y*scale])
    height = size+160
    def screen(points):
        return [tuple(p) for p in (np.asarray(points)*scale+offset)]
    base = Image.new("RGB", (size, height), BACKGROUND)
    draw = ImageDraw.Draw(base)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 22)
        small = ImageFont.truetype("DejaVuSans.ttf", 16)
    except OSError:
        font = ImageFont.load_default(size=22)
        small = ImageFont.load_default(size=16)
    draw.text((36, 26), "S V A R A K O L A M", fill=CHALK, font=font)
    draw.text((36, 58), "ONE THREAD / A MELODY IN MOTION", fill=GOLD, font=small)
    for point in geometry["dots"]:
        px, py = screen([point])[0]
        r = max(2, .047*scale)
        draw.ellipse((px-r, py-r, px+r, py+r), fill=GOLD)
    width = max(2, round(STROKE*scale))
    samples = [screen(cubic(s["points"], np.linspace(0, 1, 25))) for s in geometry["segments"]]
    # Incremental base drawing amortizes completed segments across all frames.
    completed = 0
    frames = math.ceil(analysis["duration"]*fps)
    try:
        with imageio.get_writer(str(destination), format="FFMPEG", fps=fps,
                                codec="libx264", quality=8, macro_block_size=2,
                                audio_path=str(audio_path), audio_codec="aac",
                                output_params=["-t", str(analysis["duration"]), "-movflags", "+faststart"],
                                ffmpeg_log_level="error") as writer:
            for frame in range(frames):
                t = min(analysis["duration"], frame/fps)
                # Last frame closes the line; audio length is the authoritative end.
                q = 1. if frame == frames-1 else progress_at(geometry, t)
                distance = q*geometry["length"]
                target = min(len(samples), bisect.bisect_right(geometry["cumulative"], distance)-1)
                while completed < target:
                    ImageDraw.Draw(base).line(samples[completed], fill=CHALK, width=width, joint="curve")
                    completed += 1
                image = base.copy()
                draw = ImageDraw.Draw(image)
                if completed < len(samples):
                    segment = geometry["segments"][completed]
                    available = max(0, distance-geometry["cumulative"][completed])
                    u = np.interp(available, segment["lut"], np.linspace(0, 1, len(segment["lut"])))
                    draw.line(screen(cubic(partial_curve(segment["points"], u), np.linspace(0, 1, 25))),
                              fill=CHALK, width=width, joint="curve")
                for bridge in weave_bridges(geometry, q):
                    points = screen(np.vstack([cubic(c, np.linspace(0, 1, 12)) for c in bridge]))
                    draw.line(points, fill=BACKGROUND, width=max(width+2, round(width*3.2)), joint="curve")
                    draw.line(points, fill=CHALK, width=width, joint="curve")
                note, beat = active_hud(analysis, t)
                # ASCII swara notation supports systems without an Indic font.
                swara = note["swara"].replace("—", "rest")
                draw.text((36, height-46), f"{swara}    |    Beat {beat}/{analysis['tala']}    |    {t:05.1f}s",
                          fill=CHALK, font=font)
                writer.append_data(np.asarray(image))
                if frame % fps == 0:
                    report(frame/frames, f"Rendering {frame//fps}s / {analysis['duration']:.0f}s")
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    if not destination.exists() or destination.stat().st_size < 1024:
        raise RuntimeError("FFmpeg did not produce a valid video.")
