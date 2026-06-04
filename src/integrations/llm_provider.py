"""
LLM provider unificado con contexto del proyecto.

Jerarquía de providers:
  1. airllm (local, GPU, gratis, sin internet)
  2. Groq API (gratis, 30 req/min)
  3. Gemini API (gratis, 15 req/min)
  4. None (el ejercicio usa su fallback heurístico)

El system prompt se construye dinámicamente desde:
  - MANIFIESTO.md (propósito del canal - estático)
  - knowledge_base (insights aprendidos - dinámico)
  - Métricas actuales (qué funciona - dinámico)
  - Curriculum plan (qué sigue - dinámico)

Esto asegura que cada generación del LLM entiende:
  1. POR QUÉ existe el canal
  2. QUÉ ha funcionado antes
  3. QUÉ hay que mejorar
  4. PARA QUIÉN es el contenido

Uso:
  from integrations.llm_provider import LLMProvider

  llm = LLMProvider(settings, conn=db_connection)
  result = llm.generate(
      prompt="Clasifica esta frase: 'I am your father'",
      task_type="classification",  # narration, classification, analysis, planning
      max_tokens=300,
  )
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

import requests
from utils.http_client import get_session

if TYPE_CHECKING:
    import sqlite3
    from core.config import Settings


# ---------------------------------------------------------------------------
# Context builders (the "memory" the LLM sees)
# ---------------------------------------------------------------------------

_MANIFESTO_CACHE: str | None = None


def _load_manifesto() -> str:
    """Load MANIFIESTO.md once, cache it."""
    global _MANIFESTO_CACHE
    if _MANIFESTO_CACHE is not None:
        return _MANIFESTO_CACHE

    # Try multiple possible locations
    for path in [
        Path("MANIFIESTO.md"),
        Path(__file__).parent.parent.parent / "MANIFIESTO.md",
    ]:
        if path.exists():
            _MANIFESTO_CACHE = path.read_text(encoding="utf-8")
            return _MANIFESTO_CACHE

    _MANIFESTO_CACHE = ""
    return _MANIFESTO_CACHE


def _get_recent_insights(conn, limit: int = 8) -> list[dict]:
    """Get the most confident, active insights from knowledge_base."""
    if conn is None:
        return []
    try:
        cur = conn.execute("""
            SELECT title, content, confidence, source
            FROM knowledge_base
            WHERE is_active = 1
            ORDER BY confidence DESC, created_at DESC
            LIMIT ?
        """, (limit,))
        return [dict(r) for r in cur.fetchall()]
    except Exception:
        return []


def _get_channel_metrics(conn) -> dict:
    """Get current channel performance summary."""
    if conn is None:
        return {}
    try:
        cur = conn.execute("""
            SELECT
                COUNT(*) as total_shorts,
                COALESCE(SUM(views), 0) as total_views,
                COALESCE(AVG(retention_avg), 0) as avg_retention,
                COALESCE(AVG(engagement_rate), 0) as avg_engagement
            FROM analytics
            WHERE platform = 'youtube' AND views > 0
        """)
        row = cur.fetchone()
        return dict(row) if row else {}
    except Exception:
        return {}


def _get_curriculum_context(conn) -> list[dict]:
    """Get next planned content from curriculum."""
    if conn is None:
        return []
    try:
        cur = conn.execute("""
            SELECT target_learning_type, target_category, target_emotion
            FROM curriculum_plan
            WHERE status = 'planned'
            ORDER BY position
            LIMIT 3
        """)
        return [dict(r) for r in cur.fetchall()]
    except Exception:
        return []


def _get_best_performing(conn) -> dict:
    """Get what content types perform best."""
    if conn is None:
        return {}
    try:
        cur = conn.execute("""
            SELECT q.category, q.emotion, q.learning_type,
                   AVG(a.retention_avg) as avg_ret,
                   COUNT(*) as n
            FROM quotes q
            JOIN shorts s ON s.quote_ids LIKE '%' || q.id || '%'
            JOIN analytics a ON a.short_id = s.id
            WHERE a.retention_avg > 0 AND q.category IS NOT NULL
            GROUP BY q.category
            HAVING n >= 2
            ORDER BY avg_ret DESC
            LIMIT 5
        """)
        rows = [dict(r) for r in cur.fetchall()]
        return {"top_categories": rows} if rows else {}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------

# Task-specific instructions
TASK_INSTRUCTIONS = {
    "classification": """Tu tarea es CLASIFICAR contenido de cine.
Responde SIEMPRE en JSON válido. Sé preciso y consistente.
Usa las categorías y emociones del proyecto (ver contexto).""",

    "narration": """Tu tarea es escribir GUIONES DE NARRACIÓN para YouTube Shorts.
Las narraciones van entre clips de película. Deben ser:
- Cortas (max 15 palabras por segmento)
- Reflexivas, nunca superficiales
- En el idioma que se te indique
- Conectar la escena con una lección de vida
Responde en JSON array.""",

    "analysis": """Tu tarea es ANALIZAR datos del canal y generar insights.
Sé específico, usa los datos disponibles. No inventes métricas.
Si los datos son insuficientes, dilo explícitamente.""",

    "planning": """Tu tarea es PLANIFICAR contenido futuro.
Equilibra: lo que retiene mejor + diversidad pedagógica + cobertura de áreas.
Sugiere queries concretas para buscar clips.""",

    "lesson": """Tu tarea es extraer LECCIONES DE VIDA de frases de cine.
Cada frase enseña algo. Identifica:
- Tipo de aprendizaje (critical_thinking, emotional_intelligence, ethics,
  creativity, resilience, self_awareness, empathy, decision_making)
- Lección universal (en español, una oración)
- Área curricular (character, relationships, society, self, conflict)
Responde en JSON.""",
}


def build_system_prompt(
    task_type: str = "classification",
    conn=None,
    extra_context: str = "",
    compact: bool = False,
) -> str:
    """
    Build a context-aware system prompt from the project's current state.

    This is the key piece: every LLM call carries the channel's purpose,
    what has worked, and what needs improvement. The prompt adapts its
    verbosity based on provider constraints:

    - compact=False (default, for APIs): full context with insights,
      metrics, curriculum, and best performers
    - compact=True (for airllm/small context): only identity + task
    """
    parts = []

    # 1. Identity and purpose (always included)
    parts.append("=== CONTEXTO DEL PROYECTO ===")
    parts.append("Canal de YouTube Shorts que extrae enseñanzas del cine.")
    parts.append("Público: personas sin mentor que buscan reflexión en contenido digital.")
    parts.append("Mantra: 'De todo se puede aprender. Y el más inteligente es el que puede aprender de todo.'")
    parts.append("El contenido forma pensamiento crítico a través del cine, NUNCA es superficial.")
    parts.append("")

    # For APIs with large context windows: include everything
    if not compact:
        # 2. What has worked (dynamic)
        insights = _get_recent_insights(conn, limit=6)
        if insights:
            parts.append("=== LO QUE SABEMOS (insights aprendidos) ===")
            for ins in insights:
                parts.append(f"- [{ins.get('source', '?')}] {ins['title']} (confianza: {ins.get('confidence', 0):.0%})")
            parts.append("")

        # 3. Current metrics
        metrics = _get_channel_metrics(conn)
        if metrics and metrics.get("total_shorts", 0) > 0:
            parts.append("=== MÉTRICAS ACTUALES ===")
            parts.append(f"- Shorts publicados: {metrics.get('total_shorts', 0)}")
            parts.append(f"- Views totales: {metrics.get('total_views', 0):,}")
            parts.append(f"- Retención promedio: {metrics.get('avg_retention', 0):.1f}%")
            parts.append(f"- Engagement promedio: {metrics.get('avg_engagement', 0):.4f}")
            parts.append("")

        # 4. Best performing content
        best = _get_best_performing(conn)
        if best.get("top_categories"):
            parts.append("=== QUÉ RETIENE MEJOR ===")
            for cat in best["top_categories"][:3]:
                parts.append(
                    f"- {cat['category']}: ret={cat['avg_ret']:.1f}% (n={cat['n']})"
                )
            parts.append("")

        # 5. What's planned next
        curriculum = _get_curriculum_context(conn)
        if curriculum:
            parts.append("=== PRÓXIMO CONTENIDO PLANIFICADO ===")
            for item in curriculum:
                parts.append(
                    f"- {item['target_learning_type']} | {item['target_category']} | {item['target_emotion']}"
                )
            parts.append("")

    # 6. Task-specific instructions (always included)
    task_instr = TASK_INSTRUCTIONS.get(task_type, TASK_INSTRUCTIONS["classification"])
    parts.append(f"=== TU TAREA ===")
    parts.append(task_instr)

    if extra_context:
        parts.append("")
        parts.append(extra_context)

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# airllm provider (local GPU inference)
# ---------------------------------------------------------------------------

_AIRLLM_MODEL = None
_AIRLLM_MODEL_ID: str | None = None

# Default model: Qwen2.5-7B-Instruct
# - Excelente en español
# - Buen output estructurado (JSON)
# - Corre en cualquier GPU con airllm (carga capa por capa)
# - 4bit compression para velocidad
DEFAULT_MODEL = "Qwen/Qwen2.5-7B-Instruct"


def _get_airllm_model(model_id: str | None = None):
    """Get or create the airllm model (singleton, lazy load)."""
    global _AIRLLM_MODEL, _AIRLLM_MODEL_ID

    model_id = model_id or os.getenv("AIRLLM_MODEL", DEFAULT_MODEL)

    if _AIRLLM_MODEL is not None and _AIRLLM_MODEL_ID == model_id:
        return _AIRLLM_MODEL

    try:
        from airllm import AutoModel
    except ImportError:
        return None

    try:
        compression = os.getenv("AIRLLM_COMPRESSION", "4bit")
        if compression not in ("4bit", "8bit"):
            compression = None

        max_seq_len = int(os.getenv("AIRLLM_MAX_SEQ_LEN", "512"))
        hf_token = os.getenv("HF_TOKEN", "")

        _AIRLLM_MODEL = AutoModel.from_pretrained(
            model_id,
            compression=compression,
            max_seq_len=max_seq_len,
            hf_token=hf_token or None,
        )
        _AIRLLM_MODEL_ID = model_id
        return _AIRLLM_MODEL
    except Exception:
        return None


def _generate_airllm(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 300,
    model_id: str | None = None,
) -> str | None:
    """Generate text using airllm (local GPU)."""
    model = _get_airllm_model(model_id)
    if model is None:
        return None

    # Build chat-style prompt (Qwen2.5 / Llama 3 format)
    full_prompt = (
        f"<|im_start|>system\n{system_prompt}<|im_end|>\n"
        f"<|im_start|>user\n{user_prompt}<|im_end|>\n"
        f"<|im_start|>assistant\n"
    )

    try:
        input_tokens = model.tokenizer(
            [full_prompt],
            return_tensors="pt",
            return_attention_mask=False,
            truncation=True,
            max_length=model.max_seq_len,
            padding=False,
        )

        generation_output = model.generate(
            input_tokens["input_ids"].cuda(),
            max_new_tokens=max_tokens,
            use_cache=True,
            return_dict_in_generate=True,
        )

        output = model.tokenizer.decode(
            generation_output.sequences[0],
            skip_special_tokens=True,
        )

        # Extract only the assistant's response
        if "<|im_start|>assistant" in output:
            output = output.split("<|im_start|>assistant")[-1]
        # Clean up any remaining tags
        output = output.replace("<|im_end|>", "").strip()

        return output if output else None

    except Exception:
        return None


# ---------------------------------------------------------------------------
# API providers (fallback)
# ---------------------------------------------------------------------------

def _generate_groq(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 300,
) -> str | None:
    """Generate via Groq API (free tier) with session reuse + retry."""
    key = os.getenv("GROQ_API_KEY", "")
    if not key:
        return None

    session = get_session("groq")
    try:
        resp = session.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": "llama-3.1-8b-instant",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.6,
                "max_tokens": max_tokens,
            },
            timeout=20,
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
        if resp.status_code == 429:
            import logging, time
            logging.getLogger(__name__).warning("Groq rate limited, waiting 5s")
            time.sleep(5)
            resp = session.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": "llama-3.1-8b-instant",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.6,
                    "max_tokens": max_tokens,
                },
                timeout=20,
            )
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"]
    except Exception:
        pass
    return None


def _generate_gemini(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 300,
) -> str | None:
    """Generate via Gemini API (free tier) with session reuse + retry."""
    key = os.getenv("GEMINI_API_KEY", "")
    if not key:
        return None

    session = get_session("gemini")
    try:
        resp = session.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={key}",
            headers={"Content-Type": "application/json"},
            json={
                "systemInstruction": {"parts": [{"text": system_prompt}]},
                "contents": [{"parts": [{"text": user_prompt}]}],
                "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.6},
            },
            timeout=20,
        )
        if resp.status_code == 200:
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        if resp.status_code == 429:
            import logging, time
            retry_after = float(resp.headers.get("Retry-After", 10))
            logging.getLogger(__name__).warning(f"Gemini rate limited, waiting {retry_after}s")
            time.sleep(retry_after)
            resp = session.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={key}",
                headers={"Content-Type": "application/json"},
                json={
                    "systemInstruction": {"parts": [{"text": system_prompt}]},
                    "contents": [{"parts": [{"text": user_prompt}]}],
                    "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.6},
                },
                timeout=20,
            )
            if resp.status_code == 200:
                return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Main provider class
# ---------------------------------------------------------------------------

class LLMProvider:
    """
    Unified LLM provider with project context awareness.

    Every generation carries the channel's purpose, learned insights,
    current metrics, and improvement goals in the system prompt.

    Provider cascade (auto mode):
      1. Gemini  - 1M context window, ideal para system prompts largos
      2. Groq    - 8K context, rápido, buen JSON
      3. airllm  - offline fallback, GPU local, contexto limitado (~512 tokens)

    Las APIs gratuitas son mejores para el pipeline porque:
      - Context window grande = cabe todo el contexto del proyecto
      - Velocidad: 1-2s vs 2-5min con airllm capa por capa
      - JSON más confiable
    airllm es para operación offline o modelos sin API gratuita.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        conn: sqlite3.Connection | None = None,
        preferred_provider: str = "auto",
    ):
        self.settings = settings
        self.conn = conn
        self.preferred_provider = preferred_provider  # auto, gemini, groq, airllm
        self._provider_used: str | None = None

    @property
    def provider_used(self) -> str | None:
        """Which provider was used in the last generation."""
        return self._provider_used

    def generate(
        self,
        prompt: str,
        task_type: str = "classification",
        max_tokens: int = 300,
        extra_context: str = "",
        temperature: float = 0.6,
    ) -> str | None:
        """
        Generate text with project-aware context.

        Args:
            prompt: The specific task prompt
            task_type: classification, narration, analysis, planning, lesson
            max_tokens: Max output tokens
            extra_context: Additional context for this specific call
            temperature: Creativity (0.0-1.0)

        Returns:
            Generated text or None if all providers fail
        """
        # Provider cascade
        providers = self._get_provider_order()

        for provider_name, provider_fn in providers:
            # airllm has limited context — use compact system prompt
            compact = (provider_name == "airllm")

            system_prompt = build_system_prompt(
                task_type=task_type,
                conn=self.conn,
                extra_context=extra_context,
                compact=compact,
            )

            result = provider_fn(system_prompt, prompt, max_tokens)
            if result:
                self._provider_used = provider_name
                return result

        self._provider_used = None
        return None

    def generate_json(
        self,
        prompt: str,
        task_type: str = "classification",
        max_tokens: int = 500,
        extra_context: str = "",
    ) -> list | dict | None:
        """Generate and parse JSON output."""
        result = self.generate(
            prompt=prompt,
            task_type=task_type,
            max_tokens=max_tokens,
            extra_context=extra_context + "\nResponde SOLO en JSON válido.",
        )
        if not result:
            return None

        # Try to extract JSON from the response
        # Handle both [...] and {...} patterns
        for pattern in [r"\[.*\]", r"\{.*\}"]:
            match = re.search(pattern, result, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    continue

        # Try parsing the whole response
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return None

    def _get_provider_order(self):
        """Get ordered list of (name, fn) based on preference."""
        # Default order: APIs first (faster, bigger context), local last
        all_providers = [
            ("gemini", _generate_gemini),    # 1M context, best for rich system prompts
            ("groq", _generate_groq),        # 8K context, fast
            ("airllm", _generate_airllm),    # Offline fallback, limited context
        ]

        if self.preferred_provider == "auto":
            return all_providers

        # Put preferred first, keep others as fallback
        ordered = []
        for name, fn in all_providers:
            if name == self.preferred_provider:
                ordered.insert(0, (name, fn))
            else:
                ordered.append((name, fn))
        return ordered

    def is_available(self) -> bool:
        """Check if any provider is available."""
        if os.getenv("GROQ_API_KEY") or os.getenv("GEMINI_API_KEY"):
            return True
        try:
            from airllm import AutoModel
            return True
        except ImportError:
            return False

    def available_providers(self) -> list[str]:
        """List which providers are configured."""
        available = []
        try:
            import airllm
            available.append("airllm")
        except ImportError:
            pass
        if os.getenv("GROQ_API_KEY"):
            available.append("groq")
        if os.getenv("GEMINI_API_KEY"):
            available.append("gemini")
        return available
