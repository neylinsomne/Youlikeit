FROM python:3.11-slim

WORKDIR /workspace

# System deps: FFmpeg + OpenCV
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

# Python deps (fuente de verdad de integraciones/librerías)
# requirements-gpu.txt incluye la base (requirements.txt) + lo pesado (OCR, whisper, scenedetect...)
COPY requirements.txt requirements-gpu.txt ./
RUN pip install --no-cache-dir -r requirements-gpu.txt

# Editable install del paquete: expone core/utils/apps/integrations/cli como
# imports limpios (sin sys.path hacks) y el CLI `ylk` en el PATH. Con el
# bind-mount ./:/workspace en runtime, apunta al código vivo del repo.
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir -e . --no-deps

# cuBLAS/cuDNN de los wheels nvidia-*-cu12 (faster-whisper/CTranslate2 en GPU)
ENV LD_LIBRARY_PATH=/usr/local/lib/python3.11/site-packages/nvidia/cublas/lib:/usr/local/lib/python3.11/site-packages/nvidia/cudnn/lib

# EasyOCR models download on first use (cached in volume)
ENV EASYOCR_MODULE_PATH=/workspace/data/.easyocr
