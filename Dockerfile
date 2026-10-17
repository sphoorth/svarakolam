FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SVARAKOLAM_DATA=/data \
    IMAGEIO_FFMPEG_EXE=/usr/bin/ffmpeg \
    NUMBA_CACHE_DIR=/tmp/numba \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1

# System FFmpeg also supports architectures without a bundled imageio binary.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libsndfile1 libgomp1 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app \
    && mkdir -p /data \
    && chown app:app /data

WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install -r requirements.txt
COPY --chown=app:app main.py ./
COPY --chown=app:app core/ ./core/
COPY --chown=app:app static/ ./static/

USER app
EXPOSE 8000

# One worker is required: sessions and job indexes are held in process memory.
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
