FROM fishaudio/fish-speech:v1.4.1

# Install CUDA 12.8 runtime libs needed by PyTorch nightly
RUN pip install --pre torch torchaudio \
    --index-url https://download.pytorch.org/whl/nightly/cu128 \
    --force-reinstall && \
    pip install nvidia-cusparselt-cu12
