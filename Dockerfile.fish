FROM fishaudio/fish-speech:v1.4.1

# Install torch + torchaudio nightly cu128 for Blackwell (sm_120) + all CUDA runtime libs
RUN pip install --pre torch torchaudio \
    --index-url https://download.pytorch.org/whl/nightly/cu128 \
    --force-reinstall && \
    pip install nvidia-cusparselt-cu12 nvidia-cufile-cu12 soundfile

# Ensure pip-installed NVIDIA .so files are discoverable by torch
ENV LD_LIBRARY_PATH="/usr/local/lib/python3.12/site-packages/nvidia/cufile/lib:/usr/local/lib/python3.12/site-packages/nvidia/cusparselt/lib:${LD_LIBRARY_PATH}"

# Patch: replace torchaudio.load with soundfile in api.py
COPY fish-speech-audio-patch.py /tmp/
RUN python3 /tmp/fish-speech-audio-patch.py
