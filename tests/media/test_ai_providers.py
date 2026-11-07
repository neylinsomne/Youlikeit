"""Capa de IA intercambiable: ASR por API (Groq) y LLM JSON en cascada."""
from __future__ import annotations

import pytest

from apps.media import transcribe
from integrations.ai import asr_api, llm_json


# ── ASR por API ─────────────────────────────────────────────────────


@pytest.mark.unit
def test_plan_audio_chunks_overlap_and_cover():
    assert asr_api.plan_audio_chunks(300_000) == [(0, 300_000)]
    plan = asr_api.plan_audio_chunks(1_500_000, chunk_ms=600_000, overlap_ms=2_000)
    assert plan == [(0, 600_000), (598_000, 1_198_000), (1_196_000, 1_500_000)]


@pytest.mark.unit
def test_merge_chunks_absolute_times_without_duplicates():
    # El segmento "dup" cae en el solape: lo trae el tramo 1 y el 2; debe quedar una vez.
    c1 = {"language": "English",
          "segments": [{"start": 1.0, "end": 2.0, "text": " hello"},
                       {"start": 598.5, "end": 599.6, "text": " dup"}],
          "words": [{"word": "hello", "start": 1.0, "end": 1.5}, {"word": "dup", "start": 598.5, "end": 599.0}]}
    c2 = {"language": "English",
          "segments": [{"start": 0.5, "end": 1.6, "text": " dup"},
                       {"start": 3.0, "end": 4.0, "text": " world"}],
          "words": [{"word": "dup", "start": 0.5, "end": 1.0}, {"word": "world", "start": 3.0, "end": 3.4}]}
    segs = asr_api.merge_chunks([(0, 600_000, c1), (598_000, 1_000_000, c2)], overlap_ms=2_000)
    assert [s["text"] for s in segs] == ["hello", "dup", "world"]
    assert segs[2]["start_ms"] == 601_000 and segs[2]["words"][0]["start_ms"] == 601_000
    assert segs[0]["lang"] == "en"


@pytest.mark.integration
def test_transcribe_groq_with_mocked_http(mocked_http, monkeypatch, tmp_path):
    monkeypatch.setattr(asr_api, "_encode_chunk", lambda wav, s, e, out: (out.write_bytes(b"mp3"), out)[1])
    mocked_http.post(asr_api.GROQ_ASR_URL, json={
        "language": "spanish",
        "segments": [{"start": 0.2, "end": 1.4, "text": " Ya vienen por ti", "avg_logprob": -0.2,
                      "no_speech_prob": 0.01}],
        "words": [{"word": "Ya", "start": 0.2, "end": 0.4}, {"word": "vienen", "start": 0.4, "end": 0.8}]})
    segs, lang = asr_api.transcribe_groq(tmp_path / "a.wav", duration_ms=5_000, api_key="test")
    assert lang == "es"
    assert segs[0]["text"] == "Ya vienen por ti" and len(segs[0]["words"]) == 2
    body = mocked_http.calls[0].request.body
    assert b"timestamp_granularities" in body and b"verbose_json" in body


@pytest.mark.unit
def test_transcribe_groq_requires_key(monkeypatch, tmp_path):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        asr_api.transcribe_groq(tmp_path / "a.wav", duration_ms=1000)


@pytest.mark.unit
def test_resolve_backend_auto(monkeypatch):
    monkeypatch.setattr(transcribe, "local_cuda_available", lambda: False)
    monkeypatch.setenv("GROQ_API_KEY", "x")
    assert transcribe.resolve_backend("auto") == "groq"
    monkeypatch.setattr(transcribe, "local_cuda_available", lambda: True)
    assert transcribe.resolve_backend("auto") == "local"
    assert transcribe.resolve_backend("groq") == "groq"
    with pytest.raises(ValueError):
        transcribe.resolve_backend("openai")


# ── LLM JSON ────────────────────────────────────────────────────────

SCHEMA = {"type": "object", "required": ["trope", "confidence"],
          "properties": {"trope": {"type": "string", "enum": ["mentor_betrayal", "refusal_of_the_call"]},
                         "confidence": {"type": "number"}}}


@pytest.mark.unit
def test_validate_and_parse():
    assert llm_json.validate({"trope": "mentor_betrayal", "confidence": 0.8}, SCHEMA) == []
    errs = llm_json.validate({"trope": "otro"}, SCHEMA)
    assert any("enum" in e for e in errs) and any("confidence" in e for e in errs)
    assert llm_json.parse_json('<think>hmm</think>```json\n{"a": 1}\n```') == {"a": 1}


@pytest.mark.unit
def test_provider_order(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq,gemini")
    assert llm_json.provider_order() == ["groq", "gemini"]
    assert llm_json.provider_order("auto") == ["ollama", "groq", "gemini"]
    with pytest.raises(ValueError):
        llm_json.provider_order("chatgpt")


@pytest.mark.integration
def test_complete_json_cascades_past_invalid_answer(mocked_http, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setenv("GEMINI_API_KEY", "m")
    monkeypatch.setattr(llm_json, "available", lambda name: name != "ollama")
    mocked_http.post("https://api.groq.com/openai/v1/chat/completions", json={
        "choices": [{"message": {"content": '{"trope": "inventado", "confidence": 0.9}'}}]})
    mocked_http.post(f"https://generativelanguage.googleapis.com/v1beta/models/"
                     f"{llm_json.model_for('gemini')}:generateContent",
                     json={"candidates": [{"content": {"parts": [
                         {"text": '{"trope": "mentor_betrayal", "confidence": 0.7}'}]}}]})
    data, used = llm_json.complete_json("¿Qué tropo?", schema=SCHEMA, provider="auto")
    assert used == "gemini" and data["trope"] == "mentor_betrayal"


@pytest.mark.unit
def test_complete_json_without_providers_raises(monkeypatch):
    monkeypatch.setattr(llm_json, "available", lambda name: False)
    with pytest.raises(llm_json.LLMUnavailable):
        llm_json.complete_json("x", schema=SCHEMA)


@pytest.mark.integration
def test_groq_429_waits_and_retries(mocked_http, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    waits = []
    monkeypatch.setattr(llm_json.time, "sleep", lambda s: waits.append(s))
    url = "https://api.groq.com/openai/v1/chat/completions"
    mocked_http.post(url, status=429, body="Rate limit reached. Please try again in 1.5s.")
    mocked_http.post(url, json={"choices": [{"message": {"content": '{"trope": "siege", "confidence": 0.6}'}}]})
    monkeypatch.setattr(llm_json, "available", lambda name: name == "groq")
    data, used = llm_json.complete_json("x", schema={"type": "object", "required": ["trope"],
                                                     "properties": {"trope": {"type": "string"}}})
    assert used == "groq" and data["trope"] == "siege"
    assert waits == [2.0]


@pytest.mark.integration
def test_groq_json_validate_failed_is_retried(mocked_http, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    url = "https://api.groq.com/openai/v1/chat/completions"
    mocked_http.post(url, status=400, json={"error": {"code": "json_validate_failed", "message": "bad json"}})
    mocked_http.post(url, json={"choices": [{"message": {"content": '{"ok": true}'}}]})
    monkeypatch.setattr(llm_json, "available", lambda name: name == "groq")
    data, used = llm_json.complete_json("x", schema={"type": "object"})
    assert data == {"ok": True} and used == "groq"


@pytest.mark.unit
def test_groq_reasoning_models_get_low_effort_and_token_margin():
    p = llm_json.groq_payload("s", "p", model="openai/gpt-oss-120b", temperature=0.5, max_tokens=780)
    assert p["reasoning_effort"] == "low" and p["max_tokens"] == 780 + llm_json.REASONING_BUDGET
    retry = llm_json.groq_payload("s", "p", model="openai/gpt-oss-120b", temperature=0.5, max_tokens=780, attempt=1)
    assert retry["max_tokens"] > p["max_tokens"]                     # más margen en cada reintento
    plain = llm_json.groq_payload("s", "p", model="qwen/qwen3.8-27b", temperature=0.5, max_tokens=780)
    assert "reasoning_effort" not in plain and plain["max_tokens"] == 780
