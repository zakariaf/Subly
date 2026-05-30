# syntax=docker/dockerfile:1.7
#
# Subly runtime image. ffmpeg is baked in because the pipeline shells out to
# the ffmpeg/ffprobe CLIs for audio extraction and subtitle burn-in
# (subtrans/audio.py, subtrans/video.py). libgomp1 is the OpenMP runtime that
# faster-whisper's ctranslate2/onnxruntime backends need at import time.
#
# Fonts: this slim image ships none, so libass would render burned-in subtitles
# as blank/boxes. fonts-dejavu-core covers Latin (our default FontName); the Noto
# core set covers Persian/Arabic (Noto Sans Arabic) plus Hebrew and other scripts.
# Kurdish (Sorani) is the exception — the Noto Arabic faces fake its letters with
# detachable marks that render disconnected — so we vendor IRANBlack, which has
# genuine joined Kurdish glyphs (see the COPY below).

FROM python:3.12-slim-bookworm

WORKDIR /app

# Acquire::Retries makes apt retry transient download failures (flaky mirrors/proxies)
# instead of aborting the whole build on a single dropped package.
RUN apt-get update -o Acquire::Retries=8 \
    && apt-get install -y --no-install-recommends -o Acquire::Retries=8 \
        ffmpeg libgomp1 fontconfig fonts-dejavu-core fonts-noto-core \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Vendored Kurdish font (IRANBlack) so Kurdish burns render the same here as in our
# tests, instead of relying on the base image's (mis-shaping) Noto Arabic faces.
COPY assets/fonts/ /usr/local/share/fonts/subly/
RUN fc-cache -f

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
