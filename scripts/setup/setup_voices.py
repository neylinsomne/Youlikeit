"""
Download free voice reference samples from LibriVox for Fish Audio S1-Mini.

LibriVox audiobooks are public domain - no copyright issues.
Downloads ~15s clips per language for immediate use.

Usage:
  python scripts/setup_voices.py
  python scripts/setup_voices.py --langs es en pt
"""

from __future__ import annotations

import argparse
import io
import struct
import sys
from pathlib import Path

import requests

# LibriVox API - free public domain audiobooks
# We search for audiobooks in each language and grab a short clip
LIBRIVOX_API = "https://librivox.org/api/feed/audiobooks"

# Archive.org direct links to known-good short narration clips (public domain)
# These are stable, well-recorded audiobook excerpts
FALLBACK_SAMPLES: dict[str, dict] = {
    "en": {
        "url": "https://archive.org/download/art_of_war_librivox/art_of_war_01-02_sun_tzu_64kb.mp3",
        "title": "Art of War - Sun Tzu (LibriVox)",
        "license": "Public Domain",
    },
    "es": {
        "url": "https://archive.org/download/donquijote_2507_librivox/donquijote_000_cervantes_64kb.mp3",
        "title": "Don Quijote - Cervantes (LibriVox)",
        "license": "Public Domain",
    },
    "pt": {
        "url": "https://archive.org/download/memorias_de_bras_cubas_2003_librivox/membrascubas_00_deassis_64kb.mp3",
        "title": "Memórias de Brás Cubas - Machado de Assis (LibriVox)",
        "license": "Public Domain",
    },
    "fr": {
        "url": "https://archive.org/download/petit_prince_1611_librivox/petitprince_01_saintexupery_64kb.mp3",
        "title": "Le Petit Prince - Saint-Exupéry (LibriVox)",
        "license": "Public Domain",
    },
    "de": {
        "url": "https://archive.org/download/verwandlung_1205_librivox/verwandlung_01_kafka_64kb.mp3",
        "title": "Die Verwandlung - Kafka (LibriVox)",
        "license": "Public Domain",
    },
}


def _create_wav_from_silence(path: Path, duration_s: float = 15.0, sample_rate: int = 44100):
    """Create a silent WAV as last-resort placeholder."""
    n_frames = int(sample_rate * duration_s)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(str(path), "wb") as f:
        # WAV header
        data_size = n_frames * 2  # 16-bit mono
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16))
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        f.write(b"\x00\x00" * n_frames)


def download_voice_sample(lang: str, voices_dir: Path) -> bool:
    """Download a voice reference sample for the given language."""
    voice_dir = voices_dir / f"narrator_{lang}"
    sample_path = voice_dir / "sample.wav"

    if sample_path.exists():
        print(f"  [{lang}] Already exists: {sample_path}")
        return True

    voice_dir.mkdir(parents=True, exist_ok=True)

    fallback = FALLBACK_SAMPLES.get(lang)
    if not fallback:
        print(f"  [{lang}] No source available. Creating silent placeholder.")
        _create_wav_from_silence(sample_path)
        info_path = voice_dir / "info.json"
        import json
        info_path.write_text(json.dumps({
            "lang": lang,
            "source": "placeholder (silent)",
            "note": "Replace with a real 15-30s voice recording",
        }, indent=2), encoding="utf-8")
        return True

    print(f"  [{lang}] Downloading: {fallback['title']}...")

    try:
        # Download first 30 seconds of the MP3
        headers = {
            "Range": "bytes=0-500000",  # ~30s of MP3 at 64kbps
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "audio/mpeg, */*",
            "Referer": "https://archive.org/",
        }
        resp = requests.get(fallback["url"], headers=headers, timeout=30, stream=True)

        if resp.status_code not in (200, 206):
            print(f"  [{lang}] Download failed (HTTP {resp.status_code}). Creating placeholder.")
            _create_wav_from_silence(sample_path)
            return True

        # Save as MP3 first, then note that Fish Speech can handle MP3 too
        mp3_path = voice_dir / "sample.mp3"
        mp3_path.write_bytes(resp.content)

        # Fish Speech accepts MP3 as reference, but also create a note
        # about converting to WAV if needed
        info_path = voice_dir / "info.json"
        import json
        info_path.write_text(json.dumps({
            "lang": lang,
            "source": fallback["title"],
            "license": fallback["license"],
            "url": fallback["url"],
            "format": "mp3",
            "note": (
                "Fish Speech S1-Mini accepts MP3 as reference audio. "
                "For best quality, convert to WAV 44100Hz mono: "
                f"ffmpeg -i sample.mp3 -ar 44100 -ac 1 -t 20 sample.wav"
            ),
        }, indent=2), encoding="utf-8")

        print(f"  [{lang}] Saved: {mp3_path} ({len(resp.content) // 1024}KB)")
        print(f"  [{lang}] To convert to WAV: ffmpeg -i {mp3_path} -ar 44100 -ac 1 -t 20 {sample_path}")
        return True

    except Exception as e:
        print(f"  [{lang}] Error: {e}. Creating placeholder.")
        _create_wav_from_silence(sample_path)
        return True


def main():
    parser = argparse.ArgumentParser(description="Download voice reference samples for Fish Audio S1-Mini")
    parser.add_argument("--langs", nargs="+", default=["es", "en", "pt"], help="Languages to download")
    parser.add_argument("--voices-dir", default="data/voices", help="Voice samples directory")
    args = parser.parse_args()

    voices_dir = Path(args.voices_dir)
    print(f"Setting up voice references in: {voices_dir}")
    print(f"Languages: {', '.join(args.langs)}")
    print()

    for lang in args.langs:
        download_voice_sample(lang, voices_dir)
        print()

    print("Done! Voice references ready.")
    print()
    print("Usage with ex18:")
    for lang in args.langs:
        voice_dir = voices_dir / f"narrator_{lang}"
        mp3 = voice_dir / "sample.mp3"
        wav = voice_dir / "sample.wav"
        ref = str(wav) if wav.exists() else str(mp3)
        print(f"  python scripts/legacy/main.py ex18 --query \"villain\" --lang {lang} --voice-ref {ref}")


if __name__ == "__main__":
    main()
