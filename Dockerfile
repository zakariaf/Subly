# syntax=docker/dockerfile:1.7
#
# Subly runtime image. ffmpeg is baked in because the pipeline shells out to
# the ffmpeg/ffprobe CLIs for audio extraction and subtitle burn-in
# (subtrans/audio.py, subtrans/video.py). libgomp1 is the OpenMP runtime that
# faster-whisper's ctranslate2/onnxruntime backends need at import time.

FROM python:3.12-slim-bookworm

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libgomp1 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install deps first so the layer caches across code changes.
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Only the runtime code — tests, docs, and .claude/ are excluded via .dockerignore.
COPY subtrans ./subtrans
COPY bot.py cli.py ./

# Default to the bot; Kamal overrides this per-role via `cmd:` if needed.
CMD ["python", "bot.py"]
