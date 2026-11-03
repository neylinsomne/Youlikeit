"""LLM con salida JSON estructurada, local o por API, con cascada.

Para la Fase 2 (etiquetar momentos con vocabulario controlado) y los guiones.
Proveedores:
  - ollama  local (RTX 5060). `format=<json schema>` fuerza la estructura.
  - groq    API gratis (límite por minuto). `response_format=json_object`.
  - gemini  API gratis. `responseMimeType=application/json`.
El esquema siempre va también en el prompt, y la respuesta se valida
(claves requeridas + enums) antes de aceptarla; si falla, pasa al siguiente.
"""
from __future__ import annotations

import json
import logging
import os
import re

import requests

log = logging.getLogger(__name__)

_MODEL_ENV = {
    "ollama": ("OLLAMA_MODEL", "qwen3:8b"),
    "groq": ("GROQ_LLM_MODEL", "llama-3.3-70b-versatile"),
    "gemini": ("GEMINI_MODEL", "gemini-2.5-flash"),
}


def model_for(name: str) -> str:
    """Modelo por proveedor, leído en cada llamada (el .env se carga después del import)."""
    env, default = _MODEL_ENV[name]
    return os.getenv(env) or default


def ollama_url() -> str:
    return os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")


class LLMUnavailable(RuntimeError):
    """Ningún proveedor configurado/disponible devolvió JSON válido."""


# ── validación mínima de esquema (sin dependencias) ─────────────────


def validate(data, schema: dict | None, path: str = "$") -> list[str]:
    """Valida type/required/enum/items recursivamente. Devuelve lista de errores."""
    if not schema:
        return []
    errs: list[str] = []
    t = schema.get("type")
    types = {"object": dict, "array": list, "string": str, "number": (int, float),
             "integer": int, "boolean": bool}
    if t in types and not isinstance(data, types[t]):
        return [f"{path}: se esperaba {t}"]
    if "enum" in schema and data not in schema["enum"]:
        errs.append(f"{path}: {data!r} fuera de enum")
    if t == "object":
        for key in schema.get("required", []):
            if key not in data:
                errs.append(f"{path}.{key}: requerido")
        for key, sub in (schema.get("properties") or {}).items():
            if key in data:
                errs += validate(data[key], sub, f"{path}.{key}")
    if t == "array" and "items" in schema:
        for i, item in enumerate(data):
            errs += validate(item, schema["items"], f"{path}[{i}]")
    return errs


def parse_json(text: str):
    """JSON de la respuesta, tolerando ```json fences y <think> de modelos razonadores."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"(\{.*\}|\[.*\])", text, flags=re.S)
        if not m:
            raise
        return json.loads(m.group(1))


# ── proveedores ─────────────────────────────────────────────────────


def _ollama(system: str, prompt: str, schema: dict | None, *, model: str, temperature: float,
            max_tokens: int, timeout: float) -> str:
    resp = requests.post(f"{ollama_url()}/api/chat", json={
        "model": model, "stream": False, "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "5m"),
        "format": schema or "json",
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        "options": {"temperature": temperature, "num_predict": max_tokens},
    }, timeout=timeout)
    resp.raise_for_status()
    return resp.json()["message"]["content"]


def _groq(system: str, prompt: str, schema: dict | None, *, model: str, temperature: float,
          max_tokens: int, timeout: float) -> str:
    resp = requests.post("https://api.groq.com/openai/v1/chat/completions", headers={
        "Authorization": f"Bearer {os.getenv('GROQ_API_KEY', '')}"}, json={
        "model": model, "temperature": temperature, "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
    }, timeout=timeout)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _gemini(system: str, prompt: str, schema: dict | None, *, model: str, temperature: float,
            max_tokens: int, timeout: float) -> str:
    resp = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        params={"key": os.getenv("GEMINI_API_KEY", "")}, json={
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens,
                                 "responseMimeType": "application/json"},
        }, timeout=timeout)
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


_PROVIDERS = {"ollama": _ollama, "groq": _groq, "gemini": _gemini}


def available(name: str) -> bool:
    if name == "groq":
        return bool(os.getenv("GROQ_API_KEY"))
    if name == "gemini":
        return bool(os.getenv("GEMINI_API_KEY"))
    if name == "ollama":
        try:
            tags = requests.get(f"{ollama_url()}/api/tags", timeout=2).json()
        except (requests.RequestException, ValueError):
            return False
        want = model_for("ollama")
        names = {m.get("name", "") for m in tags.get("models", [])}
        return want in names or f"{want}:latest" in names
    return False


def provider_order(spec: str | None = None) -> list[str]:
    spec = (spec or os.getenv("LLM_PROVIDER", "auto")).strip().lower()
    names = ["ollama", "groq", "gemini"] if spec == "auto" else [s.strip() for s in spec.split(",")]
    unknown = [n for n in names if n not in _PROVIDERS]
    if unknown:
        raise ValueError(f"LLM_PROVIDER desconocido: {unknown}")
    return names


def complete_json(prompt: str, *, schema: dict | None = None, system: str = "",
                  provider: str | None = None, temperature: float = 0.2,
                  max_tokens: int = 800, timeout: float = 120) -> tuple[object, str]:
    """Devuelve (json_validado, proveedor_usado). Levanta LLMUnavailable si todos fallan."""
    sys_prompt = system or "Responde SOLO con JSON válido."
    if schema:
        sys_prompt += "\nEsquema JSON obligatorio:\n" + json.dumps(schema, ensure_ascii=False)
    tried: list[str] = []
    for name in provider_order(provider):
        if not available(name):
            tried.append(f"{name}: no disponible")
            continue
        try:
            raw = _PROVIDERS[name](sys_prompt, prompt, schema, model=model_for(name),
                                   temperature=temperature, max_tokens=max_tokens, timeout=timeout)
            data = parse_json(raw)
            errs = validate(data, schema)
            if errs:
                tried.append(f"{name}: esquema inválido {errs[:3]}")
                continue
            return data, name
        except (requests.RequestException, KeyError, ValueError) as e:
            tried.append(f"{name}: {type(e).__name__} {str(e)[:120]}")
    raise LLMUnavailable("; ".join(tried) or "sin proveedores")
