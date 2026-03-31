"""Patch Fish Speech to use soundfile instead of torchaudio for loading reference audio."""
import os
import re

api_path = "/opt/fish-speech/tools/api.py"

with open(api_path) as f:
    code = f.read()

# Step 1: Remove 'import torchaudio' line entirely
code = re.sub(r'^import torchaudio\s*$', '# import torchaudio  # patched out — using soundfile', code, flags=re.MULTILINE)

# Step 2: Replace the torchaudio.load call with soundfile
old_block = '''    waveform, original_sr = torchaudio.load(
        reference_audio, backend="ffmpeg" if sys.platform == "linux" else "soundfile"
    )'''

new_block = '''    import soundfile as sf
    import numpy as np
    if isinstance(reference_audio, io.BytesIO):
        reference_audio.seek(0)
    data, original_sr = sf.read(reference_audio, dtype="float32")
    if data.ndim == 1:
        data = data[np.newaxis, :]
    else:
        data = data.T
    waveform = torch.from_numpy(data)'''

if old_block in code:
    code = code.replace(old_block, new_block)
    with open(api_path, "w") as f:
        f.write(code)
    print("Patched api.py: torchaudio.load -> soundfile + removed import")
else:
    # Try regex fallback for any torchaudio.load pattern
    if re.search(r'torchaudio\.load\(', code):
        code = re.sub(
            r'waveform, original_sr = torchaudio\.load\([^)]+\)',
            '''import soundfile as sf
    import numpy as np
    if isinstance(reference_audio, io.BytesIO):
        reference_audio.seek(0)
    data, original_sr = sf.read(reference_audio, dtype="float32")
    if data.ndim == 1:
        data = data[np.newaxis, :]
    else:
        data = data.T
    waveform = torch.from_numpy(data)''',
            code
        )
        with open(api_path, "w") as f:
            f.write(code)
        print("Patched api.py (alt pattern) + removed import")
    else:
        print("torchaudio.load not found — may already be patched")
        # Still write the import removal
        with open(api_path, "w") as f:
            f.write(code)
        print("Removed import torchaudio")
