"""Opt-in integration against a REAL user-supplied 30–60s recording.

No test downloads or generates audio. Set SVARAKOLAM_TEST_AUDIO to your clip.
"""
import os
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg
import pytest
import soundfile as sf

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.mir_extractor import extract_audio, label_analysis, normalize_audio
from core.kolam_graph import plan_grid
from core.bezier_geometry import build_geometry
from core.exporter import export_mp4


@pytest.mark.skipif(not os.environ.get("SVARAKOLAM_TEST_AUDIO"),reason="Requires a real uploaded audio recording")
def test_real_audio_to_muxed_video(tmp_path):
    source=Path(os.environ["SVARAKOLAM_TEST_AUDIO"])
    wav=tmp_path/"normalized.wav"
    raw=extract_audio(source,wav,"auto")
    analysis=label_analysis(raw,None,29,8)
    info=sf.info(wav)
    assert info.channels == 1 and info.samplerate == 22050
    assert 29.95 <= info.duration <= 60.05
    assert any(n["voiced"] for n in analysis["notes"])
    geometry=build_geometry(plan_grid(5,"ner",analysis["notes"]),analysis)
    target=tmp_path/"recording.mp4"
    export_mp4(geometry,analysis,wav,target,fps=12,size=480)
    result=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),"-i",str(target),"-f","null","-"],capture_output=True,text=True)
    assert result.returncode == 0
    assert "Video: h264" in result.stderr and "Audio: aac" in result.stderr
    assert target.stat().st_size > 10000


@pytest.mark.skipif(not os.environ.get("SVARAKOLAM_TEST_AUDIO"),reason="Requires a real uploaded audio recording")
@pytest.mark.parametrize("extension,codec",[(".wav","pcm_s16le"),(".mp3","libmp3lame"),(".flac","flac"),(".ogg","libvorbis")])
def test_real_container_normalization(tmp_path,extension,codec):
    source=Path(os.environ["SVARAKOLAM_TEST_AUDIO"])
    encoded=tmp_path/f"recording{extension}"
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),"-y","-loglevel","error","-i",str(source),
                    "-c:a",codec,str(encoded)],check=True,capture_output=True)
    normalized=tmp_path/"normalized.wav"
    _,duration=normalize_audio(encoded,normalized)
    info=sf.info(normalized)
    assert info.channels == 1 and info.samplerate == 22050
    assert 29.95 <= duration <= 60.05
