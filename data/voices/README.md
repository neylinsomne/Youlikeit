# Voice References for Fish Audio S1-Mini

Each subfolder contains a `sample.wav` (10-30s of clear speech) that S1-Mini
uses to clone the voice. The folder name becomes the voice ID.

## Structure

```
voices/
  narrator_es/
    sample.wav       ← 10-30s of Spanish narration
  narrator_en/
    sample.wav       ← 10-30s of English narration
  narrator_pt/
    sample.wav       ← 10-30s of Portuguese narration
```

## How to add your own voice

1. Record 15-30 seconds of clear speech (no background noise)
2. Save as WAV (44100 Hz, mono or stereo)
3. Create a folder with a descriptive name
4. Place the file as `sample.wav` inside

## Free voice sources

- LibriVox.org - public domain audiobooks (en, es, pt, fr, de)
- CommonVoice (Mozilla) - open voice datasets
- Your own voice - record with your phone, export as WAV
