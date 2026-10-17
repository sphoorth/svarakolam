"""Structural properties over every supported grid size, independent of audio."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.kolam_graph import plan_grid
from core.bezier_geometry import build_geometry, cubic, progress_at
from core.exporter import export_svg


@pytest.fixture
def analysis():
    # Musical metadata only. Tests never synthesize an audio waveform.
    return {"duration": 30., "notes": [
        {"start": 0., "end": 10., "voiced": True, "semitone": 0., "gamaka": 12.},
        {"start": 10., "end": 12., "voiced": False, "semitone": 0., "gamaka": 0.},
        {"start": 12., "end": 30., "voiced": True, "semitone": 7., "gamaka": 85.}]}


@pytest.mark.parametrize("grid", ["ner", "idukku"])
@pytest.mark.parametrize("size", range(2, 16))
def test_single_loop_continuity_and_dot_encirclement(grid, size, analysis):
    plan = plan_grid(size, grid, analysis["notes"])
    assert plan["loop_count"] == 1
    assert plan["degree"] == 2
    assert plan["splice_count"] == size*size-1
    assert plan["graph_edges"] == 4*size*size
    assert plan["crossing_count"] == (size-1)**2
    g = build_geometry(plan, analysis)
    segments = g["segments"]
    for i, segment in enumerate(segments):
        p, q = np.array(segment["points"]), np.array(segments[(i+1)%len(segments)]["points"])
        np.testing.assert_allclose(p[3], q[0], atol=1e-12)
        np.testing.assert_allclose(p[3]-p[2], q[1]-q[0], atol=1e-12)
    samples = np.vstack([cubic(s["points"], np.linspace(0, 1, 13)) for s in segments])
    # A winding number of +/-1 and positive clearance certify each dot is circled.
    for dot in g["dots"]:
        relative = samples-np.array(dot)
        assert np.linalg.norm(relative, axis=1).min() > .16
        angles = np.unwrap(np.arctan2(relative[:,1], relative[:,0]))
        assert abs(abs((angles[-1]-angles[0])/(2*np.pi))-1) < .02
    for cross_id in {c["id"] for c in g["crossings"]}:
        pair = [c for c in g["crossings"] if c["id"] == cross_id]
        assert len(pair) == 2 and pair[0]["over"] != pair[1]["over"]
        a, b = [np.diff(np.array(segments[c["outgoing"]]["points"])[:2],axis=0)[0] for c in pair]
        # Distinct strands must cross transversely, not form tangential kisses.
        assert abs(a[0]*b[1]-a[1]*b[0])/(np.linalg.norm(a)*np.linalg.norm(b)) > .3


def test_timeline_and_determinism(analysis):
    plan = plan_grid(7, "ner", analysis["notes"])
    g = build_geometry(plan, analysis)
    assert g == build_geometry(plan_grid(7, "ner", analysis["notes"]), analysis)
    values = [progress_at(g,t) for t in np.linspace(0,30,100)]
    assert values[0] == 0 and values[-1] == 1
    assert all(b >= a for a,b in zip(values,values[1:]))
    assert progress_at(g,12)-progress_at(g,10) < (progress_at(g,10)-progress_at(g,0))/5


def test_svg_has_one_closed_primary_path(tmp_path, analysis):
    import xml.etree.ElementTree as ET
    g = build_geometry(plan_grid(4,"ner",analysis["notes"]),analysis)
    destination = tmp_path/"kolam.svg"
    export_svg(g,destination)
    root = ET.parse(destination).getroot()
    path = root.find(".//*[@id='single-closed-circuit']")
    assert path is not None
    assert path.attrib["d"].count("M") == 1
    assert path.attrib["d"].endswith("Z")
    assert path.attrib["d"].count("C") == len(g["segments"])
