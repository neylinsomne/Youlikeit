"""Capa de IA intercambiable: LOCAL (GPU propia) o API (gratis/barata).

- asr_api   Transcripción por API (Groq Whisper large-v3-turbo, timestamps por palabra).
- llm_json  Completado con salida JSON estructurada: Ollama (local) | Groq | Gemini.

Selección por variables de entorno (ver .env.example):
    ASR_BACKEND   auto | local | groq          (auto: local si faster-whisper+CUDA, si no groq)
    LLM_PROVIDER  auto | ollama | groq | gemini  o lista "ollama,groq,gemini" (orden de cascada)
"""
