"""
ex18 - Narración reflexiva con Fish Audio OpenAudio S1-Mini.

Genera audio narrado que da "alma" al Short:
  1. Lee metadata del video (tema, emoción, frases, categoría)
  2. Un LLM genera un guión reflexivo corto (intro, transiciones, cierre)
  3. Fish Audio S1-Mini sintetiza la voz en el idioma correcto
  4. Output: archivos .wav por segmento, listos para mezclar en ex11/ex16

Soporta:
  - Cambio de idioma automático (es, en, pt, fr, de, ja, ko, zh...)
  - Voice cloning con referencia de ~10s (opcional)
  - Control de emoción/tono por segmento
  - Generación de guión con LLM gratis (Groq/Gemini) o heurístico

Uso:
  python src/main.py ex18 --query "villain monologue" --lang es
  python src/main.py ex18 --query "epic fight" --lang en --voice-ref data/voices/narrator_en.wav
  python src/main.py ex18 --query "romance" --lang pt --narration-style poetic

Requisitos:
  - Fish Audio S1-Mini corriendo como servicio (Docker o local)
  - Opcionalmente un LLM para generar el guión (Groq/Gemini gratis)
"""

from __future__ import annotations

import json
import os
import re
import wave
from datetime import datetime
from pathlib import Path

import requests

from core.config import Settings
from core.db import get_db
from utils.logger import build_logger


# ---------------------------------------------------------------------------
# Narration script templates (heuristic fallback, no LLM needed)
# ---------------------------------------------------------------------------

SCRIPT_TEMPLATES: dict[str, dict[str, list[str]]] = {
    "es": {
        "intro": [
            "A veces las mejores frases vienen de los lugares más oscuros...",
            "Hay líneas que no se olvidan, sin importar cuántas veces las escuches...",
            "El cine nos enseñó algo que la vida no pudo...",
            "Algunas palabras cambian todo...",
            "Lo que estás a punto de escuchar, lo sentiste antes de entenderlo...",
        ],
        "transition": [
            "Pero eso no fue todo...",
            "Y entonces llegó esto...",
            "Cada vez más fuerte...",
            "Esto es lo que realmente importa...",
            "Escucha bien esta...",
        ],
        "outro": [
            "Tal vez por eso el cine nunca muere.",
            "Las palabras se quedan, las películas se van.",
            "Si esto te movió algo, ya sabes qué hacer.",
            "El arte imita la vida, pero a veces la supera.",
            "Eso es todo. Pero no es poco.",
        ],
    },
    "en": {
        "intro": [
            "Sometimes the best lines come from the darkest places...",
            "There are lines you never forget, no matter how many times you hear them...",
            "Cinema taught us what life couldn't...",
            "Some words change everything...",
            "What you're about to hear, you felt before you understood it...",
        ],
        "transition": [
            "But that wasn't all...",
            "And then came this...",
            "Louder every time...",
            "This is what really matters...",
            "Listen closely to this one...",
        ],
        "outro": [
            "Maybe that's why cinema never dies.",
            "Words stay, movies fade.",
            "If this moved you, you know what to do.",
            "Art imitates life, but sometimes it surpasses it.",
            "That's all. But it's not nothing.",
        ],
    },
    "pt": {
        "intro": [
            "Às vezes as melhores frases vêm dos lugares mais sombrios...",
            "Existem falas que nunca esquecemos, não importa quantas vezes ouçamos...",
            "O cinema nos ensinou o que a vida não conseguiu...",
            "Algumas palavras mudam tudo...",
            "O que você está prestes a ouvir, sentiu antes de entender...",
        ],
        "transition": [
            "Mas isso não foi tudo...",
            "E então veio isso...",
            "Cada vez mais forte...",
            "Isso é o que realmente importa...",
            "Escute bem essa...",
        ],
        "outro": [
            "Talvez por isso o cinema nunca morra.",
            "As palavras ficam, os filmes vão.",
            "Se isso te tocou, você sabe o que fazer.",
            "A arte imita a vida, mas às vezes a supera.",
            "É isso. Mas não é pouco.",
        ],
    },
}

# Emotion-to-tone mapping for S1-Mini
EMOTION_TONE_MAP = {
    "anger": "intense and forceful",
    "joy": "warm and uplifting",
    "sadness": "soft and melancholic",
    "fear": "tense and whispered",
    "surprise": "excited and rising",
    "disgust": "cold and distant",
    "neutral": "calm and reflective",
}

# Narration styles
NARRATION_STYLES = {
    "reflective": "Calm, thoughtful narrator who connects movie quotes to deeper meaning.",
    "poetic": "Lyrical narrator who speaks in metaphors and short, impactful phrases.",
    "dramatic": "Intense narrator who builds tension between clips.",
    "casual": "Conversational narrator, like telling a friend about great movie moments.",
    "minimal": "Very few words. Let the clips speak. Only short bridges.",
}


# ---------------------------------------------------------------------------
# Script generation
# ---------------------------------------------------------------------------

def _generate_script_heuristic(
    clips: list[dict],
    query: str,
    lang: str,
    style: str = "reflective",
    emotion: str = "neutral",
) -> list[dict]:
    """Generate narration script using templates (no LLM needed)."""
    import random

    templates = SCRIPT_TEMPLATES.get(lang, SCRIPT_TEMPLATES["es"])
    random.seed(hash(query) % 2**32)  # Deterministic per query

    segments = []

    # Intro
    intro = random.choice(templates["intro"])
    segments.append({
        "type": "narration",
        "position": "intro",
        "text": intro,
        "tone": EMOTION_TONE_MAP.get(emotion, "calm and reflective"),
        "estimated_duration_s": max(2.0, len(intro.split()) * 0.35),
    })

    # Transitions between clips
    for i, clip in enumerate(clips):
        # Add the clip reference
        segments.append({
            "type": "clip",
            "position": f"clip_{i}",
            "movie_title": clip.get("movie_title", ""),
            "quote": clip.get("text", clip.get("quote", "")),
            "start_ms": clip.get("start_ms", 0),
            "end_ms": clip.get("end_ms", 0),
        })

        # Add transition if not the last clip
        if i < len(clips) - 1 and len(clips) > 2:
            transition = random.choice(templates["transition"])
            segments.append({
                "type": "narration",
                "position": f"transition_{i}",
                "text": transition,
                "tone": EMOTION_TONE_MAP.get(
                    clip.get("emotion", emotion), "calm and reflective"
                ),
                "estimated_duration_s": max(1.5, len(transition.split()) * 0.35),
            })

    # Outro
    outro = random.choice(templates["outro"])
    segments.append({
        "type": "narration",
        "position": "outro",
        "text": outro,
        "tone": EMOTION_TONE_MAP.get(emotion, "calm and reflective"),
        "estimated_duration_s": max(2.0, len(outro.split()) * 0.35),
    })

    return segments


def _generate_script_llm(
    clips: list[dict],
    query: str,
    lang: str,
    style: str = "reflective",
    emotion: str = "neutral",
) -> list[dict]:
    """Generate narration script using a free LLM (Groq or Gemini)."""

    clip_summary = "\n".join(
        f"- {c.get('movie_title', '?')}: \"{c.get('text', c.get('quote', ''))}\""
        f" (emotion: {c.get('emotion', 'neutral')}, category: {c.get('category', 'unknown')})"
        for c in clips
    )

    lang_names = {"es": "Spanish", "en": "English", "pt": "Portuguese", "fr": "French"}
    lang_name = lang_names.get(lang, "Spanish")
    style_desc = NARRATION_STYLES.get(style, NARRATION_STYLES["reflective"])

    prompt = f"""You are a narrator for a YouTube Short / TikTok video about "{query}".

Style: {style_desc}
Language: {lang_name} (write ALL narration in {lang_name})
Emotion: {emotion}

The video contains these movie clips in order:
{clip_summary}

Generate a narration script with:
1. An INTRO line (max 15 words) - hook the viewer
2. A TRANSITION line between each clip (max 10 words each) - connect the meaning
3. An OUTRO line (max 15 words) - leave an impression

Respond in JSON array format:
[
  {{"position": "intro", "text": "...", "tone": "calm and reflective"}},
  {{"position": "transition_0", "text": "...", "tone": "intense"}},
  {{"position": "outro", "text": "...", "tone": "warm"}}
]

Only narration segments, not the clips. Keep it SHORT - this is a 30 second video."""

    # Use unified LLM provider (airllm → Groq → Gemini)
    from integrations.llm_provider import LLMProvider
    llm = LLMProvider()
    result = llm.generate_json(prompt, task_type="narration", max_tokens=500)

    if not result or not isinstance(result, list):
        # Fallback to heuristic
        return _generate_script_heuristic(clips, query, lang, style, emotion)

    # Convert LLM output to our segment format
    segments = []
    narr_idx = 0
    clip_idx = 0

    for item in result:
        pos = item.get("position", "")

        # Insert clip before its transition
        if pos.startswith("transition") or pos == "outro":
            if clip_idx < len(clips):
                c = clips[clip_idx]
                segments.append({
                    "type": "clip",
                    "position": f"clip_{clip_idx}",
                    "movie_title": c.get("movie_title", ""),
                    "quote": c.get("text", c.get("quote", "")),
                    "start_ms": c.get("start_ms", 0),
                    "end_ms": c.get("end_ms", 0),
                })
                clip_idx += 1

        text = item.get("text", "")
        segments.append({
            "type": "narration",
            "position": pos,
            "text": text,
            "tone": item.get("tone", "calm and reflective"),
            "estimated_duration_s": max(1.5, len(text.split()) * 0.35),
        })

    # Add remaining clips
    while clip_idx < len(clips):
        c = clips[clip_idx]
        segments.append({
            "type": "clip",
            "position": f"clip_{clip_idx}",
            "movie_title": c.get("movie_title", ""),
            "quote": c.get("text", c.get("quote", "")),
            "start_ms": c.get("start_ms", 0),
            "end_ms": c.get("end_ms", 0),
        })
        clip_idx += 1

    return segments


# ---------------------------------------------------------------------------
# Fish Audio S1-Mini TTS
# ---------------------------------------------------------------------------

FISH_SPEECH_DEFAULTS = {
    "api_url": "http://localhost:8080",  # Local Fish Speech server
    "model": "s1-mini",
    "sample_rate": 44100,
    "format": "wav",
}

# Language code to Fish Audio language mapping
LANG_TO_FISH = {
    "es": "es",
    "en": "en",
    "pt": "pt",
    "fr": "fr",
    "de": "de",
    "ja": "ja",
    "ko": "ko",
    "zh": "zh",
}


def _preprocess_text_for_prosody(text: str, position: str) -> str:
    """
    Preprocess narration text for natural-sounding TTS.

    Adds breath marks, normalizes ellipsis into actual pauses,
    and ensures proper sentence endings so the TTS model produces
    natural falling/rising intonation.
    """
    # Trailing ellipsis sounds unfinished — give outros a real ending
    if position == "outro" and text.rstrip().endswith("..."):
        text = text.rstrip().rstrip(".") + "."

    # Mid-sentence ellipsis → comma + pause marker for breath
    text = re.sub(r"\.{3,}", ", ...", text)

    # Double dash → comma for a natural pause
    text = text.replace(" -- ", ", ")
    text = text.replace("--", ", ")

    # Ensure the text ends with punctuation (period if missing)
    stripped = text.rstrip()
    if stripped and stripped[-1] not in ".!?…":
        text = stripped + "."

    return text


def _synthesize_segment(
    text: str,
    output_path: Path,
    lang: str = "es",
    tone: str = "calm and reflective",
    voice_ref_path: str | None = None,
    api_url: str = "http://localhost:8080",
    position: str = "intro",
) -> dict:
    """
    Synthesize a single narration segment using Fish Audio S1-Mini.

    Returns metadata about the generated audio.
    """
    fish_lang = LANG_TO_FISH.get(lang, "en")

    # Preprocess text for natural prosody
    text = _preprocess_text_for_prosody(text, position)

    # Build the request for Fish Speech API
    payload: dict = {
        "text": text,
        "language": fish_lang,
        "format": "wav",
        "streaming": False,
    }

    # Add emotion/tone instruction
    # S1-Mini supports emotion tags in the text itself
    emotion_prefix = ""
    if "intense" in tone or "forceful" in tone:
        emotion_prefix = "[intense] "
    elif "warm" in tone or "uplifting" in tone:
        emotion_prefix = "[happy] "
    elif "soft" in tone or "melancholic" in tone:
        emotion_prefix = "[sad] "
    elif "tense" in tone or "whispered" in tone:
        emotion_prefix = "[whisper] "
    elif "excited" in tone:
        emotion_prefix = "[excited] "

    payload["text"] = emotion_prefix + text

    # Prosody parameters — make the voice less robotic
    prosody_params = {
        "temperature": 0.85,          # Higher = more expressive variation
        "top_p": 0.85,                # Wider sampling for natural rhythm
        "repetition_penalty": 1.12,   # Avoid monotone loops
        "chunk_length": 150,          # Shorter chunks = more natural phrasing
    }
    payload.update(prosody_params)

    headers = {"Content-Type": "application/json"}

    # If voice reference is provided, use voice cloning
    files = None
    if voice_ref_path and Path(voice_ref_path).exists():
        # Multipart request with reference audio
        files = {
            "reference_audio": open(voice_ref_path, "rb"),
        }
        # When using files, send payload as form data
        form_data = {
            "text": payload["text"],
            "language": fish_lang,
            "format": "wav",
            "temperature": str(prosody_params["temperature"]),
            "top_p": str(prosody_params["top_p"]),
            "repetition_penalty": str(prosody_params["repetition_penalty"]),
            "chunk_length": str(prosody_params["chunk_length"]),
        }
        resp = requests.post(
            f"{api_url}/v1/tts",
            data=form_data,
            files=files,
            timeout=30,
        )
    else:
        resp = requests.post(
            f"{api_url}/v1/tts",
            json=payload,
            headers=headers,
            timeout=30,
        )

    if resp.status_code != 200:
        return {
            "success": False,
            "error": f"Fish Speech API returned {resp.status_code}: {resp.text[:200]}",
            "path": None,
        }

    # Write the audio file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(resp.content)

    # Get duration from WAV header
    duration_s = 0.0
    try:
        with wave.open(str(output_path), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            duration_s = frames / rate if rate > 0 else 0
    except Exception:
        # Estimate from text
        duration_s = max(1.5, len(text.split()) * 0.35)

    return {
        "success": True,
        "path": str(output_path),
        "duration_s": round(duration_s, 2),
        "text": text,
        "lang": lang,
        "tone": tone,
    }


def _check_fish_speech_available(api_url: str) -> bool:
    """Check if Fish Speech server is running."""
    try:
        resp = requests.get(f"{api_url}/v1/models", timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


def _load_persona_voice(persona: str = "") -> dict:
    """Load voice settings from tokens/personas.json for the given persona."""
    try:
        cfg_path = Path("tokens/personas.json")
        if cfg_path.exists() and persona:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            p = cfg.get(persona, {})
            voice_cfg = p.get("voice", {})
            if voice_cfg.get("engine") == "edge-tts":
                return voice_cfg
    except Exception:
        pass
    return {}


def _synthesize_edge_tts(
    text: str,
    output_path: Path,
    lang: str = "en",
    persona: str = "",
) -> dict:
    """Synthesize speech using edge-tts (Microsoft, free, no API key)."""
    import asyncio
    import edge_tts

    # Check for persona-specific voice first
    persona_voice = _load_persona_voice(persona)

    if persona_voice:
        voice = persona_voice["name"]
        rate = persona_voice.get("rate", "-5%")
        pitch = persona_voice.get("pitch", "-5Hz")
    else:
        # Default voice selection by language
        voice_map = {
            "en": "en-US-AndrewMultilingualNeural",
            "es": "es-CO-GonzaloNeural",
            "pt": "pt-BR-AntonioNeural",
            "ja": "ja-JP-KeitaNeural",
        }
        voice = voice_map.get(lang, "en-US-AndrewMultilingualNeural")
        rate = "-10%"
        pitch = "-5Hz"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    mp3_path = output_path.with_suffix(".mp3")

    try:
        async def _do_tts():
            communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
            await communicate.save(str(mp3_path))

        asyncio.run(_do_tts())

        # Convert mp3 to wav for pipeline compatibility
        import subprocess
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(mp3_path), "-ar", "44100", "-ac", "1", str(output_path)],
            capture_output=True, timeout=15,
        )
        mp3_path.unlink(missing_ok=True)

        # Get duration
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(output_path)],
            capture_output=True, text=True, timeout=10,
        )
        duration = float(result.stdout.strip()) if result.stdout.strip() else 2.0

        return {
            "success": True,
            "placeholder": False,
            "path": str(output_path),
            "duration_s": duration,
            "text": text,
            "lang": lang,
            "voice": voice,
            "engine": "edge-tts",
        }
    except Exception as e:
        log.warning(f"edge-tts failed: {e}. Falling back to silent placeholder.")
        return _generate_placeholder_wav(output_path)


def _generate_placeholder_wav(output_path: Path, duration_s: float = 2.0, sample_rate: int = 44100) -> dict:
    """
    Generate a silent WAV placeholder when Fish Speech is not available.
    This allows the pipeline to continue without TTS - the user can
    re-run ex18 later when Fish Speech is set up.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    n_frames = int(sample_rate * duration_s)

    with wave.open(str(output_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * n_frames)

    return {
        "success": True,
        "placeholder": True,
        "path": str(output_path),
        "duration_s": duration_s,
    }


# ---------------------------------------------------------------------------
# Gather inputs from previous steps
# ---------------------------------------------------------------------------

def _gather_clips(output_dir: Path, query: str, conn) -> list[dict]:
    """Get clips from ex09 curation or ex07 manifest."""
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", query.strip())[:50] or "theme"

    # Try ex09 curation first (has scoring)
    cur_dir = output_dir / "curation"
    if cur_dir.exists():
        files = sorted(cur_dir.glob(f"ex09_curation_{slug}_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if files:
            try:
                data = json.loads(files[0].read_text(encoding="utf-8"))
                groups = data.get("groups", [])
                if groups:
                    # Take first group's clips
                    return groups[0].get("clips", [])
                candidates = data.get("top_candidates", [])
                if candidates:
                    return candidates[:5]
            except Exception:
                pass

    # Fallback: ex07 manifest
    man_dir = output_dir / "manifests"
    if man_dir.exists():
        files = sorted(man_dir.glob(f"*{slug}*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            files = sorted(man_dir.glob("short_manifest_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if files:
            try:
                data = json.loads(files[0].read_text(encoding="utf-8"))
                return data.get("clips", [])
            except Exception:
                pass

    # Last resort: get best quotes from DB
    cur = conn.execute(
        """SELECT q.*, m.title as movie_title
           FROM quotes q JOIN movies m ON q.movie_id = m.id
           WHERE q.start_ms IS NOT NULL AND q.confidence > 70
           ORDER BY q.viral_score DESC, q.confidence DESC
           LIMIT 5"""
    )
    return [dict(r) for r in cur.fetchall()]


def _detect_dominant_emotion(clips: list[dict]) -> str:
    """Detect the most common emotion across clips."""
    emotions: dict[str, int] = {}
    for c in clips:
        em = c.get("emotion", "neutral") or "neutral"
        emotions[em] = emotions.get(em, 0) + 1
    if not emotions:
        return "neutral"
    return max(emotions, key=emotions.get)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(
    settings: Settings,
    query: str = "epic movie moment",
    lang: str = "es",
    style: str = "reflective",
    voice_ref: str = "",
    fish_url: str = "",
    use_llm: bool = True,
    persona: str = "",
) -> Path:
    log = build_logger("ex18", settings.output_dir / "logs" / "ex18.log")
    conn = get_db(settings.data_dir)

    # Resolve Fish Speech URL
    api_url = fish_url or os.getenv("FISH_SPEECH_URL", "http://localhost:8080")

    # 1) Gather clips
    clips = _gather_clips(settings.output_dir, query, conn)
    if not clips:
        log.warning("No clips found. Run ex04 -> ex06 -> ex07/ex09 first.")
        out_dir = settings.output_dir / "narration"
        out_dir.mkdir(parents=True, exist_ok=True)
        no_data = out_dir / "ex18_no_clips.txt"
        no_data.write_text(
            "No hay clips. Ejecuta ex04 -> ex05 -> ex06 -> ex07/ex09 primero.",
            encoding="utf-8",
        )
        conn.close()
        return no_data

    emotion = _detect_dominant_emotion(clips)
    log.info("Found %d clips, dominant emotion: %s", len(clips), emotion)

    # 2) Generate narration script
    from integrations.llm_provider import LLMProvider
    _llm_check = LLMProvider()
    if use_llm and _llm_check.is_available():
        log.info("Generating script with LLM...")
        segments = _generate_script_llm(clips, query, lang, style, emotion)
    else:
        log.info("Generating script with heuristic templates...")
        segments = _generate_script_heuristic(clips, query, lang, style, emotion)

    # 3) Check if Fish Speech is available
    fish_available = _check_fish_speech_available(api_url)
    if fish_available:
        log.info("Fish Speech S1-Mini available at %s", api_url)
    else:
        log.warning(
            "Fish Speech not available at %s. Generating silent placeholders. "
            "Re-run ex18 after starting Fish Speech to generate real audio.",
            api_url,
        )

    # 4) Synthesize each narration segment
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", query.strip())[:50] or "theme"
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    audio_dir = settings.output_dir / "narration" / f"{slug}_{ts}"
    audio_dir.mkdir(parents=True, exist_ok=True)

    voice_ref_path = voice_ref if voice_ref else os.getenv("VOICE_REF_PATH", "")

    # Check if edge-tts is available as fallback
    edge_tts_available = False
    if not fish_available:
        try:
            import edge_tts
            edge_tts_available = True
            log.info("Using edge-tts (Microsoft TTS) for narration")
        except ImportError:
            log.info("edge-tts not installed. Using silent placeholders.")

    for seg in segments:
        if seg["type"] != "narration":
            continue

        wav_name = f"{seg['position']}_{lang}.wav"
        wav_path = audio_dir / wav_name

        if fish_available:
            result = _synthesize_segment(
                text=seg["text"],
                output_path=wav_path,
                lang=lang,
                tone=seg.get("tone", "calm and reflective"),
                voice_ref_path=voice_ref_path or None,
                api_url=api_url,
                position=seg.get("position", "intro"),
            )
        elif edge_tts_available:
            result = _synthesize_edge_tts(
                text=seg["text"],
                output_path=wav_path,
                lang=lang,
                persona=persona,
            )
            result["tone"] = seg.get("tone", "")
        else:
            est_dur = seg.get("estimated_duration_s", 2.0)
            result = _generate_placeholder_wav(wav_path, duration_s=est_dur)
            result["text"] = seg["text"]
            result["tone"] = seg.get("tone", "")
            result["lang"] = lang

        seg["audio"] = result
        if result.get("success"):
            seg["audio_path"] = str(wav_path)
            seg["audio_duration_s"] = result.get("duration_s", 0)
            log.info("  %s: %.1fs - %s", seg["position"], result.get("duration_s", 0), seg["text"][:60])
        else:
            log.error("  %s: FAILED - %s", seg["position"], result.get("error", "unknown"))

    # 5) Build narration manifest
    narration_segments = [s for s in segments if s["type"] == "narration"]
    clip_segments = [s for s in segments if s["type"] == "clip"]
    total_narration_s = sum(s.get("audio_duration_s", 0) for s in narration_segments)

    manifest = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "query": query,
        "lang": lang,
        "style": style,
        "dominant_emotion": emotion,
        "fish_speech_available": fish_available,
        "voice_ref": voice_ref_path or None,
        "total_narration_duration_s": round(total_narration_s, 2),
        "segments": segments,
        "audio_dir": str(audio_dir),
        "mixing_instructions": {
            "strategy": (
                "Los archivos .wav de narración van ENTRE los clips de película. "
                "El orden es: intro.wav -> clip_0 -> transition_0.wav -> clip_1 -> ... -> outro.wav. "
                "En ex11/ex16, concatenar en este orden con crossfade de 0.3s."
            ),
            "volume": {
                "narration": "100% (voz clara)",
                "movie_clips": "80-90% (bajar ligeramente para que la narración destaque)",
                "background_music": "15-25% (seleccionar EN LA PLATAFORMA, no mezclar aquí)",
            },
        },
    }

    manifest_path = audio_dir / "narration_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    # 6) Human-readable report
    txt_path = audio_dir / "narration_report.txt"
    lines = [
        "ex18 - Narration Report",
        "=" * 50,
        f"Query: {query}",
        f"Language: {lang}",
        f"Style: {style}",
        f"Dominant emotion: {emotion}",
        f"Fish Speech: {'CONNECTED' if fish_available else 'NOT AVAILABLE (placeholders generated)'}",
        f"Voice ref: {voice_ref_path or 'default'}",
        f"Total narration: {total_narration_s:.1f}s",
        "",
        "Script:",
        "-" * 40,
    ]

    for seg in segments:
        if seg["type"] == "narration":
            dur = seg.get("audio_duration_s", seg.get("estimated_duration_s", 0))
            placeholder = " [PLACEHOLDER]" if seg.get("audio", {}).get("placeholder") else ""
            lines.append(f"  [{seg['position']}] ({dur:.1f}s{placeholder}) {seg['tone']}")
            lines.append(f"    \"{seg['text']}\"")
            lines.append("")
        else:
            lines.append(f"  [{seg['position']}] {seg.get('movie_title', '?')}")
            lines.append(f"    \"{seg.get('quote', '')[:100]}\"")
            lines.append("")

    lines.append("Mixing order:")
    for seg in segments:
        if seg["type"] == "narration":
            lines.append(f"  -> NARRATION: {seg.get('audio_path', 'N/A')}")
        else:
            lines.append(f"  -> CLIP: {seg.get('movie_title', '?')} [{seg.get('start_ms', 0)}-{seg.get('end_ms', 0)}ms]")

    if not fish_available:
        lines.append("")
        lines.append("NOTA: Fish Speech no está corriendo. Los .wav son silencio.")
        lines.append("Para generar audio real:")
        lines.append("  1. docker compose up -d fish-speech")
        lines.append("  2. python src/main.py ex18 --query \"...\" --lang es")

    txt_path.write_text("\n".join(lines), encoding="utf-8")

    conn.close()
    log.info("Narration manifest saved to %s", manifest_path)
    return manifest_path
