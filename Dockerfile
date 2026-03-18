FROM mcr.microsoft.com/playwright/python:v1.54.0-jammy

WORKDIR /workspace

# Install project dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# FFmpeg with NVENC support (GPU accelerated encoding)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*
