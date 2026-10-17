"""Upload-only MIR. No learned model is trained and no audio is synthesized."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

import imageio_ffmpeg
import librosa
import numpy as np
import soundfile as sf
from scipy.ndimage import median_filter
from scipy.signal import savgol_filter
from scipy.stats import gaussian_kde

SR = 22050
HOP = 256


def normalize_audio(source: Path, destination: Path) -> tuple[np.ndarray, float]:
    """Bundled FFmpeg decodes all accepted containers, including MP3 on Windows.

    Limit decoding to 61 seconds before loading into memory. Extra-long media is
    rejected, never silently truncated into an acceptable upload.
    """
    command = [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
               "-nostdin", "-y", "-i", str(source), "-t", "61", "-vn", "-ac", "1",
               "-ar", str(SR), "-c:a", "pcm_s16le", str(destination)]
    try:
        subprocess.run(command, capture_output=True, check=True, timeout=45)
        y, sr = sf.read(destination, dtype="float32")
    except (subprocess.SubprocessError, RuntimeError, OSError) as exc:
        raise ValueError("This audio could not be decoded. Upload a valid WAV, MP3, FLAC, or OGG file.") from exc
    duration = len(y) / sr
    if not 29.95 <= duration <= 60.05:
        raise ValueError(f"Upload a 30–60 second clip (received {duration:.1f} seconds or longer).")
    if not np.isfinite(y).all() or np.max(np.abs(y)) < .0001:
        raise ValueError("The clip contains no usable audio signal.")
    y = librosa.resample(y, orig_sr=sr, target_sr=SR) if sr != SR else y
    peak = float(np.max(np.abs(y)))
    y = y * (.95 / peak)
    sf.write(destination, y, SR, subtype="PCM_16")
    return y, len(y) / SR


def estimate_tonic(f0: np.ndarray) -> tuple[float, float]:
    """Circular octave-folded KDE, not a claim of raga/tonic identification.

    A pitch-density mode is a starting estimate: an instrument's most persistent
    note need not be Sa. The studio always allows a tonic override.
    """
    voiced = f0[np.isfinite(f0) & (f0 > 0)]
    if len(voiced) < 10:
        raise ValueError("Too little stable monophonic pitch was detected. Try a clearer solo recording.")
    midi = librosa.hz_to_midi(voiced)
    pc = np.mod(midi, 12)
    # Downsample deterministically to bound KDE evaluation cost.
    pc = pc[::max(1, len(pc)//1800)]
    extended = np.r_[pc-12, pc, pc+12]
    kde = gaussian_kde(extended, bw_method=.025)
    grid = np.linspace(0, 12, 1200, endpoint=False)
    density = kde(grid)
    mode = float(grid[np.argmax(density)])
    # Sa in the lower-middle singing octave; the octave is explicitly editable.
    reference_midi = mode + 12 * np.floor((np.percentile(midi, 35)-mode)/12)
    tonic = float(librosa.midi_to_hz(reference_midi))
    while tonic < 80:
        tonic *= 2
    while tonic > 400:
        tonic /= 2
    confidence = float(np.clip((density.max()/max(density.mean(), 1e-9)-1)/6, 0, 1))
    return tonic, confidence


def extract_audio(source: Path, destination: Path, tracker: str = "auto",
                  report: Callable[[float, str], None] = lambda *_: None) -> dict:
    report(.03, "Decoding and normalizing uploaded audio")
    y, duration = normalize_audio(source, destination)
    report(.10, "Extracting monophonic pitch; first run may compile pYIN")
    f0 = confidence = None
    method, warnings = "librosa.pyin", []
    if tracker in {"auto", "crepe"}:
        try:
            import torch
            import torchcrepe
            if not torch.cuda.is_available():
                raise RuntimeError("No CUDA device")
            audio16 = librosa.resample(y, orig_sr=SR, target_sr=16000)
            with torch.inference_mode():
                tensor = torch.tensor(audio16, device="cuda").unsqueeze(0)
                pitch, periodicity = torchcrepe.predict(
                    tensor, 16000, 160, 65, 1600, model="full", batch_size=1024,
                    device="cuda", return_periodicity=True)
            raw = pitch[0].detach().cpu().numpy()
            prob = periodicity[0].detach().cpu().numpy()
            raw[prob < .3] = np.nan
            target = librosa.frames_to_time(np.arange(1+len(y)//HOP), sr=SR, hop_length=HOP)
            source_times = np.arange(len(raw))*.01
            idx = np.minimum(np.searchsorted(source_times, target), len(raw)-1)
            f0, confidence = raw[idx], prob[idx]
            if np.count_nonzero(np.isfinite(f0)) < 10:
                raise RuntimeError("CREPE did not detect enough stable pitch")
            method = "torchcrepe (CUDA)"
        except Exception:
            # Optional libraries and driver/model failures must never disable pYIN.
            warnings.append("CUDA CREPE unavailable; used the CPU pYIN pitch tracker.")
            f0 = confidence = None
    if f0 is None:
        f0, voiced, confidence = librosa.pyin(y, sr=SR, hop_length=HOP,
                                             frame_length=2048, fmin=65., fmax=1600.,
                                             fill_na=np.nan)
        f0 = np.where(voiced & (confidence >= .1), f0, np.nan)
    report(.65, "Estimating Sa, note onsets and beat pulse")
    mask = np.isfinite(f0)
    # Smooth within voiced islands only: never interpolate across a silence.
    cents = np.full_like(f0, np.nan, dtype=float)
    cents[mask] = 1200*np.log2(f0[mask])
    boundaries = np.flatnonzero(np.diff(np.r_[False, mask, False]))
    for a, b in zip(boundaries[::2], boundaries[1::2]):
        window = min(9, (b-a if (b-a) % 2 else b-a-1))
        if window >= 5:
            cents[a:b] = savgol_filter(cents[a:b], window, 2)
    f0[mask] = 2**(cents[mask]/1200)
    tonic, tonic_confidence = estimate_tonic(f0)
    onset = librosa.onset.onset_detect(y=y, sr=SR, hop_length=HOP, units="time", backtrack=False)
    tempo, beats = librosa.beat.beat_track(y=y, sr=SR, hop_length=HOP, units="time", trim=False)
    frame_times = librosa.frames_to_time(np.arange(len(f0)), sr=SR, hop_length=HOP)
    # Include sustained pitch changes missed by transient onset detection.
    midi = np.where(mask, librosa.hz_to_midi(np.where(mask, f0, 440)), np.nan)
    filled = np.where(mask, midi, 0)
    stable = median_filter(filled, size=11)
    changes = np.flatnonzero((np.abs(np.diff(stable)) >= .8) |
                             (np.diff(mask.astype(int)) != 0)) + 1
    candidates = sorted(set([0., duration] + onset.tolist() + frame_times[changes].tolist()))
    edges = [0.]
    for t in candidates[1:-1]:
        if t-edges[-1] >= .10 and duration-t >= .10:
            edges.append(t)
    edges.append(duration)
    notes = []
    for a, b in zip(edges, edges[1:]):
        selector = (frame_times >= a) & (frame_times < b)
        valid = f0[selector & mask]
        voiced = len(valid) >= max(2, np.count_nonzero(selector)*.3)
        if voiced:
            hz = float(np.median(valid))
            local_cents = 1200*np.log2(valid/hz)
            variance = float(np.std(local_cents))
            coverage = float(np.mean(confidence[selector & mask]))
        else:
            hz, variance, coverage = None, 0., 0.
        notes.append(dict(start=float(a), end=float(b), hz=hz, gamaka=min(variance, 300.),
                          voiced=bool(voiced), confidence=coverage))
    report(.92, "Building musical timeline")
    # Store modestly downsampled pitch and waveform data for responsive plotting.
    step = max(1, len(f0)//1800)
    waveform = np.array_split(y, min(600, len(y)))
    return dict(duration=duration, sample_rate=SR, estimated_tonic=tonic,
                tonic_confidence=tonic_confidence, tracker=method, warnings=warnings,
                tempo=float(np.asarray(tempo).reshape(-1)[0]), beats=beats.tolist(),
                onsets=onset.tolist(), notes=notes,
                pitch=[dict(time=float(frame_times[i]), hz=float(f0[i]) if mask[i] else None)
                       for i in range(0, len(f0), step)],
                waveform=[float(np.max(np.abs(block))) for block in waveform])


def label_analysis(raw: dict, tonic: float | None, mela: int, tala: int) -> dict:
    sa = tonic or raw["estimated_tonic"]
    notes = []
    for note in raw["notes"]:
        n = dict(note)
        if n["voiced"]:
            n["semitone"] = float(12*np.log2(n["hz"]/sa))
            n["swara"] = str(librosa.hz_to_svara_c(n["hz"], Sa=sa, mela=mela,
                                                  unicode=False, octave=True))
        else:
            n.update(swara="—", semitone=0.)
        notes.append(n)
    return {**raw, "notes": notes, "tonic": sa, "mela": mela, "tala": tala}
