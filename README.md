# SvaraKolam

A local FastAPI studio that turns **your uploaded 30–60 second solo recording** into a single closed Sikku/Brahma Mudi diagram, drawn in musical time. WAV, MP3, FLAC, and OGG are decoded to a normalized mono WAV. There is no audio generator, bundled demo recording, model training, or frontend build step.

For hosting on your own server, see [DEPLOYMENT.md](DEPLOYMENT.md). Docker, Compose, an HTTPS reverse proxy, and shared studio login configuration are included.

## Run on Windows, macOS, or Linux

Use Python 3.10 or newer (Python 3.11 is verified).

```powershell
cd svarakolam
python -m venv .venv
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```

The studio opens at **http://127.0.0.1:8000**. Use `python main.py --no-browser --port 8001` to change launch behavior. FFmpeg comes with `imageio-ffmpeg`; a separate system installation is unnecessary. Linux needs the system `libsndfile` library if a matching SoundFile wheel is unavailable. The first pYIN run may take longer while Numba compiles its kernels.

For optional GPU pitch tracking, install compatible `torch` and `torchcrepe` packages for your CUDA installation. The app attempts CREPE only with a usable CUDA device and catches optional-import, model, inference, and driver errors before falling back to pYIN. `pYIN · CPU` bypasses the optional stack entirely. No optional model is downloaded unless CREPE is actually invoked.

## Use the studio

1. Upload a clear 30–60 second monophonic flute, violin, veena, or vocal excerpt, at most 32 MB. Stereo containers are mixed to mono; multiple simultaneous notes are outside the pitch tracker's assumptions.
2. Musical controls are collapsed under **Advanced settings** by default. Open them if you want to check Sa by ear, choose a Melakarta for swara spelling, or change tala pulse grouping. Automatic Sa is an octave-folded pitch-density mode, **not a reliable identification of tonic**. An empty tonic field restores the estimate.
3. Choose Ner Pulli (N×N) or Idukku Pulli (1, 2, …, N, …, 2, 1 staggered rows), N=2–15. Change Sa, Melakarta, tala pulse grouping, or the grid without re-uploading or rerunning MIR.
4. Play, pause, restart, or seek. Space toggles playback outside form controls. The audio element's playback clock controls drawing and HUD state; animation does not accumulate a separate clock. Seeking backward reconstructs the corresponding path prefix.
5. Download the complete lossless SVG or start an asynchronous H.264/AAC MP4 export with the normalized uploaded audio and live swara/pulse overlays. Video is 960×1120 at 30 fps. Export uses the exact saved design, even if you subsequently change settings.

The preview before upload displays only topology, with no musical events or fabricated recording.

## Why the line is one loop

`kolam_graph.py` places a four-corner cycle around each pulli on an underlying square lattice. A deterministic, swara/gamaka-weighted minimum spanning tree chooses V−1 facing-side splices. Each splice merges two distinct components; because the splice graph is a tree it cannot join a component to itself. The result has V−(V−1)=1 component, and every corner retains degree two.

The solver verifies connectedness, degree two, and Eulerian status, then traverses the entire circuit with NetworkX's Hierholzer implementation. There is no generate-and-retry loop repair. For non-tree adjacencies, two distinct topological strand vertices share a geometric position. Their transverse tangents and fixed continuation encode a four-valent medial crossing without creating extra circuits. The diagram is a constructive contemporary Sikku family, not a claim to reproduce every traditional Brahma Mudi motif or symmetry.

`bezier_geometry.py` constructs periodic cubic Hermite segments. The incoming and outgoing control offsets at each anchor are identical, so the derivative matches at all joins, including the closing join. Bounded gamaka modulation changes control reach while preserving those constraints. Idukku is an orthonormal rotation of the lattice, retaining the same invariants. Visual overpasses are background-colored bridge underlays plus chalk redraws; they never cut the primary closed SVG path.

The timeline assigns successive sections of path length to successive note/rest intervals. Onsets and sustained pitch changes define boundaries; pitch and gamaka influence density and curvature. Rests advance more slowly. This is a deterministic visual mapping of musical features, not a notation transcription or beat-for-stroke bijection. Browser and video both interpolate the same length lookup tables and timeline. The last video frame closes the curve within one frame of the audio endpoint.

## MIR interpretation

- Bundled FFmpeg decodes at most 61 seconds; longer input is rejected rather than accepted after silent truncation. Duration boundaries allow 50 ms of decoder tolerance. Peak normalization targets 0.95, at 22050 Hz mono PCM16.
- pYIN tracks 65–1600 Hz. Savitzky–Golay smoothing acts only within voiced islands and preserves unvoiced gaps. Optional CUDA CREPE uses its pretrained model.
- Circular KDE estimates a persistent pitch class as an editable Sa candidate. There is no raga recognition, instrument recognition, or custom training.
- `librosa.hz_to_svara_c` provides Melakarta-context swara notation using a **12-tone equal-tempered approximation**. Gamaka is the within-event pitch standard deviation in cents; it is not a classification of named Carnatic ornaments.
- `onset_detect` supplies transients; stable pitch changes and voiced transitions add event boundaries. `beat_track` estimates a pulse and tempo. **Tala is a user-selected grouping of detected pulses**, anchored at the first detected beat. This does not infer eduppu, nadai, samam, or tala identity. Nonmetrical alapana may have no meaningful beat track.

## Modules and API

```text
requirements.txt
main.py
core/__init__.py
core/mir_extractor.py
core/kolam_graph.py
core/bezier_geometry.py
core/exporter.py
static/index.html
static/style.css
static/app.js
```

Additional `tests/` and this README cover verification and operation. Interactive API documentation: `/docs`.

| Endpoint | Behavior |
| --- | --- |
| `POST /api/analyze` | Multipart `file`, optional `tracker=auto/pyin/crepe`; returns job/session IDs (202) |
| `GET /api/jobs/{id}` | Job state, progress, message; completed analysis includes the design |
| `POST /api/preview` | Grid-only geometry; JSON settings, no audio |
| `POST /api/sessions/{id}/design` | JSON `grid`, `size`, `mela`, `tonic`, `tala`; returns immutable design |
| `GET /api/sessions/{id}/audio` | Normalized WAV with browser byte-range support |
| `GET /api/designs/{id}/svg` | Complete, closed vector drawing |
| `POST /api/designs/{id}/mp4` | Queues export; returns job ID (202) |
| `GET /api/jobs/{id}/video` | Downloads a completed MP4 |
| `DELETE /api/sessions/{id}` | Deletes idle session, original-derived WAV, and exports |
| `GET /api/health` | Process health |

## Runtime and deployment scope

The default is a **single-process local studio** bound to loopback, with two background worker threads. Jobs and indexes live in memory. Restarting the process invalidates session IDs; it does not resume jobs. Do not launch multiple Uvicorn workers against this in-memory registry. A public multiuser service needs authentication, an external job queue and persistent session store, ingress request limits, and per-user quotas before deployment.

At most 12 sessions are retained, and the video queue is bounded. Uploaded originals are removed after analysis succeeds or fails. Normalized audio and exports live in `.runtime/` (override with `SVARAKOLAM_DATA`). Sessions expire after 24 hours and cleanup runs on subsequent uploads or deletion; startup removes abandoned runtime folders older than 24 hours. An explicit delete button removes an idle session immediately. No user audio is sent to an external service. Avoid using a shared runtime folder for multiple server processes.

Pitch analysis can be CPU-intensive; video rendering streams frames to FFmpeg instead of retaining a movie in RAM. Failures appear in the studio while detailed diagnostics stay in server logs. Settings validation, random resource IDs, a decoded duration cap, upload limits, and scoped file responses constrain resource access. Use a process manager and an isolated runtime directory if packaging this for unattended operation.

## Verification

```powershell
python -m pip install pytest httpx
python -m pytest tests -q
```

The structural/API suite tests all supported grid sizes and both layouts, C1 closure, winding around every dot, dot clearance, transverse strand pairing, deterministic geometry, chronological progress, one primary closed SVG path, request validation, recomputation without MIR, and deletion. The opt-in integration test requires a **real** 30–60 second recording; tests never synthesize audio:

```powershell
$env:SVARAKOLAM_TEST_AUDIO = 'C:\path\to\your\solo-recording.wav'
python -m pytest tests/test_real_audio.py -q -s
```

It runs actual analysis, normalization, rendering, and a complete FFmpeg decode, checking for H.264 video and AAC audio streams. On macOS/Linux use `SVARAKOLAM_TEST_AUDIO=/path/clip.wav python -m pytest tests/test_real_audio.py -q`.

Reference APIs: [librosa Carnatic notation](https://librosa.org/doc/0.11.0/generated/librosa.hz_to_svara_c.html), [pYIN](https://librosa.org/doc/0.11.0/generated/librosa.pyin.html), [NetworkX Eulerian circuits](https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.euler.eulerian_circuit.html), [imageio FFmpeg writer](https://imageio.readthedocs.io/en/stable/_autosummary/imageio.plugins.ffmpeg.html).

Implementation verification used a 30-second excerpt (beginning at 5 seconds) of Scott Goff's live solo-flute performance, *Joachim Andersen — Etude Op. 15 No. 3*, from [Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Joachim_Andersen_-_Etude_3_for_Solo_Flute.oga), licensed [CC BY-SA 2.0](https://creativecommons.org/licenses/by-sa/2.0/). The excerpt was cropped and mixed to mono solely for local testing; it is not bundled with the application. This Western flute recording checks the engineering pipeline, not Carnatic transcription accuracy. Representative Carnatic listening evaluation remains necessary to assess musical fidelity.
