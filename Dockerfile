FROM python:3.11-slim

WORKDIR /workspace

# System deps: FFmpeg + OpenCV
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# EasyOCR models download on first use (cached in volume)
ENV EASYOCR_MODULE_PATH=/workspace/data/.easyocr
