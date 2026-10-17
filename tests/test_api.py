import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main,"DATA",tmp_path)
    # Avoid shutting down the shared executor between independent tests.
    return TestClient(main.app)


def test_static_health_and_preview(client):
    assert client.get("/").status_code == 200
    assert client.get("/api/health").json()["status"] == "ok"
    response = client.post("/api/preview", json={"size": 5,"grid":"idukku"})
    assert response.status_code == 200
    assert response.json()["topology"]["loop_count"] == 1


@pytest.mark.parametrize("settings",[{"size":1},{"size":16},{"grid":"bogus"},{"mela":73},{"tonic":0},{"tonic":1001},{"tala":2}])
def test_validation(client, settings):
    assert client.post("/api/preview", json=settings).status_code == 422


def test_upload_rejection_and_missing_resources(client):
    assert client.post("/api/analyze",files={"file":("music.exe",b"invalid")}).status_code == 415
    assert client.post("/api/analyze",files={"file":("empty.wav",b"")}).status_code == 422
    assert client.post("/api/analyze",files={"file":("clip.wav",b"invalid")},data={"tracker":"bad"}).status_code == 422
    assert client.get("/api/jobs/unknown").status_code == 404
    assert client.get("/api/designs/unknown/svg").status_code == 404


def test_recompute_does_not_reanalyze_and_exports_svg(client, monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("MIR must not be rerun for parameter edits")
    monkeypatch.setattr(main,"extract_audio",unexpected)
    key = uuid.uuid4().hex
    folder = main.DATA/key
    folder.mkdir()
    raw = dict(duration=30.,estimated_tonic=130.8,tonic_confidence=.5,
               notes=[dict(start=0.,end=30.,hz=196.,gamaka=20.,voiced=True,confidence=.9)],
               beats=[0.,.5,1.],onsets=[0.],pitch=[],waveform=[],sample_rate=22050,
               tracker="test metadata",warnings=[],tempo=120.)
    main.sessions[key] = dict(created=__import__('time').time(),raw=raw,busy=False)
    try:
        one = client.post(f"/api/sessions/{key}/design",json={"size":3}).json()
        two = client.post(f"/api/sessions/{key}/design",json={"size":6,"grid":"idukku","tonic":196,"mela":65}).json()
        assert one["geometry"]["topology"]["dot_count"] == 9
        assert two["geometry"]["topology"]["dot_count"] == 36
        assert two["analysis"]["notes"][0]["swara"] == "S"
        svg = client.get(f"/api/designs/{two['id']}/svg")
        assert svg.status_code == 200 and "single-closed-circuit" in svg.text
        assert client.delete(f"/api/sessions/{key}").status_code == 204
        assert not folder.exists()
        assert client.get(f"/api/designs/{two['id']}/svg").status_code == 404
    finally:
        main.sessions.pop(key,None)
