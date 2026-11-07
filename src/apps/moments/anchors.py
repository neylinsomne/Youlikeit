"""Anclas externas: qué momentos de una obra ya están documentados como importantes.

- Wikiquote: frases célebres y diálogos → se buscan en la transcripción
  (cascada portada de ex06.find_best_match: exacta → difusa en ventanas de
  1-3 segmentos, con prefiltro por tokens). Una cita encontrada = momento con
  respaldo externo fuerte. Monólogos largos se anclan por su comienzo y final.
- Wikipedia (sección Plot): cada frase de la trama se alinea a una ventana de
  la transcripción con TF-IDF + programación dinámica MONÓTONA (la trama va en
  orden) y un prior de posición. Da contexto ("qué está pasando acá") y la
  posición narrativa real de cada momento.

Licencias: Wikiquote/Wikipedia son CC BY-SA; los textos se usan como índice y
contexto interno, no se republican en los videos.
"""
from __future__ import annotations

import logging
import re

import numpy as np

from apps.moments.text import Tfidf, cosine_matrix, fuzzy_ratio, normalize, tokens
from utils.http_client import api_get

log = logging.getLogger(__name__)

UA = {"User-Agent": "YouLikeIt/1.0 (supercut research; https://github.com/neylinsomne/Youlikeit)"}
SKIP_SECTIONS = {"taglines", "cast", "external links", "see also", "about", "quotes about",
                 "references", "notes", "reparto", "enlaces externos", "véase también"}
MIN_QUOTE_TOKENS = 3
QUOTE_THRESHOLD = 0.82


# ── limpieza de wikitext ────────────────────────────────────────────


def clean_wikitext(text: str) -> str:
    text = re.sub(r"<ref[^>]*?/>|<ref.*?</ref>", "", text, flags=re.S)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"\{\{[^{}]*\}\}", "", text)
    text = re.sub(r"\[\[(?:File|Image|Archivo):[^\]]*\]\]", "", text, flags=re.I)
    text = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"''\s*\[[^\]]*\]\s*''", "", text)          # ''[acotación]''
    text = re.sub(r"\[[^\]]*\]", "", text)
    text = text.replace("'''", "").replace("''", "")
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_wikiquote(wikitext: str) -> list[dict]:
    """Citas de una página de película de Wikiquote: [{text, speaker, section}]."""
    quotes, section = [], ""
    for raw in wikitext.splitlines():
        line = raw.strip()
        m = re.match(r"^=+\s*(.*?)\s*=+$", line)
        if m:
            section = clean_wikitext(m.group(1))
            continue
        if normalize(section) in SKIP_SECTIONS or not line or line.startswith(("**", "::")):
            continue
        speaker = None
        if line.startswith(":"):
            dm = re.match(r"^:\s*'''(.+?)'''\s*:\s*(.*)$", line)
            if not dm:
                continue                                       # acotación o texto suelto
            speaker, body = clean_wikitext(dm.group(1)), dm.group(2)
        elif line.startswith("*"):
            body = line.lstrip("* ")
            speaker = section or None
        else:
            continue
        text = clean_wikitext(body)
        if len(tokens(text, drop_stopwords=False)) >= MIN_QUOTE_TOKENS:
            quotes.append({"text": text, "speaker": speaker, "section": section})
    return quotes


def parse_plot(wikitext: str) -> list[str]:
    """Frases de la sección de trama."""
    body = "\n".join(ln for ln in wikitext.splitlines() if not ln.strip().startswith("=="))
    text = clean_wikitext(body)
    sents = re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÑ\"'])", text)
    return [s.strip() for s in sents if len(s.split()) >= 4]


# ── descarga (MediaWiki API) ────────────────────────────────────────


def _search_page(site: str, query: str) -> list[str]:
    data = api_get(f"https://{site}/w/api.php", params={
        "action": "query", "list": "search", "srsearch": query, "format": "json", "srlimit": 6},
        service="wikimedia", headers=UA)
    return [r["title"] for r in ((data or {}).get("query") or {}).get("search", [])]


def _pick_title(candidates: list[str], title: str, year: int | None) -> str | None:
    def score(c: str) -> float:
        base = re.sub(r"\s*\(.*\)$", "", c)
        s = fuzzy_ratio(base, title) if len(base) >= len(title) * 0.6 else 0.0
        if year and str(year) in c:
            s += 0.3
        if re.search(r"\((19|20)\d\d film\)", c) and year and str(year) not in c:
            s -= 0.5                                           # otra versión (remake)
        if "series" in c.lower() or "films" in c.lower():
            s -= 0.3
        return s
    best = max(candidates, key=score, default=None)
    return best if best and score(best) >= 0.8 else None


def exact_title_candidates(title: str, year: int | None) -> list[str]:
    """Títulos exactos en orden de preferencia (convención de Wikipedia/Wikiquote)."""
    out = [f"{title} ({year} film)"] if year else []
    return out + [f"{title} (film)", title]


def _resolve_exact(site: str, title: str, year: int | None) -> str | None:
    """Primera página existente y no-desambiguación entre los títulos exactos.

    La búsqueda de texto completo de Wikiquote ordena mal ("Horror Express 1972
    film" devolvía páginas de personas); consultar títulos exactos es más fiable.
    """
    cands = exact_title_candidates(title, year)
    data = api_get(f"https://{site}/w/api.php", params={
        "action": "query", "titles": "|".join(cands), "redirects": 1, "prop": "pageprops",
        "ppprop": "disambiguation", "format": "json"}, service="wikimedia", headers=UA)
    q = (data or {}).get("query") or {}
    alias = {n["from"]: n["to"] for n in q.get("normalized", []) + q.get("redirects", [])}
    ok = {p["title"] for p in (q.get("pages") or {}).values()
          if "missing" not in p and "invalid" not in p and "disambiguation" not in (p.get("pageprops") or {})}
    for c in cands:
        target = alias.get(alias.get(c, c), alias.get(c, c))
        if target in ok:
            return target
    return None


def _page_wikitext(site: str, page: str, section: int | str | None = None) -> str:
    params = {"action": "parse", "page": page, "prop": "wikitext", "format": "json", "redirects": 1}
    if section is not None:
        params["section"] = section
    data = api_get(f"https://{site}/w/api.php", params=params, service="wikimedia", headers=UA)
    return (((data or {}).get("parse") or {}).get("wikitext") or {}).get("*", "")


YEAR_TOLERANCE = 2


def year_matches(text: str, year: int, tolerance: int = YEAR_TOLERANCE) -> bool:
    """El año de una película varía según la fuente (estreno local vs internacional):
    Horror Express es 1972 en IA y 1973 en Wikiquote; Grave of the Vampire, 1974 vs 1972."""
    return any(str(y) in text for y in range(year - tolerance, year + tolerance + 1))


def _resolve_page(site: str, title: str, year: int | None) -> str | None:
    """Título exacto verificado (el año aparece en la página) o, si no, búsqueda."""
    page = _resolve_exact(site, title, year)
    if page and (not year or page.endswith(f"({year} film)") or year_matches(_page_wikitext(site, page, 0), year)):
        return page
    return _pick_title(_search_page(site, f"{title} {year or ''} film"), title, year)


def fetch_wikiquote(title: str, year: int | None = None, *, lang: str = "en") -> tuple[list[dict], str | None]:
    site = f"{lang}.wikiquote.org"
    page = _resolve_page(site, title, year)
    if not page:
        return [], None
    return parse_wikiquote(_page_wikitext(site, page)), f"https://{site}/wiki/{page.replace(' ', '_')}"


def fetch_plot(title: str, year: int | None = None, *, lang: str = "en") -> tuple[list[str], str | None]:
    site = f"{lang}.wikipedia.org"
    page = _resolve_page(site, title, year)
    if not page:
        return [], None
    secs = api_get(f"https://{site}/w/api.php", params={
        "action": "parse", "page": page, "prop": "sections", "format": "json", "redirects": 1},
        service="wikimedia", headers=UA)
    names = ("plot", "synopsis", "plot summary", "argumento", "sinopsis", "trama")
    idx = next((s["index"] for s in ((secs or {}).get("parse") or {}).get("sections", [])
                if normalize(s["line"]) in names), None)
    if idx is None:
        return [], None
    data = api_get(f"https://{site}/w/api.php", params={
        "action": "parse", "page": page, "prop": "wikitext", "section": idx, "format": "json",
        "redirects": 1}, service="wikimedia", headers=UA)
    wikitext = (((data or {}).get("parse") or {}).get("wikitext") or {}).get("*", "")
    return parse_plot(wikitext), f"https://{site}/wiki/{page.replace(' ', '_')}"


# ── citas ↔ transcripción ───────────────────────────────────────────


def build_windows(segments: list[dict], max_span: int = 3,
                  max_gap_ms: int = 3000) -> list[tuple[int, int, str, set]]:
    """Ventanas de 1..max_span segmentos CONTIGUOS (huecos < max_gap_ms), precalculadas una vez."""
    out = []
    for i in range(len(segments)):
        for j in range(i, min(i + max_span, len(segments))):
            if j > i and segments[j]["start_ms"] - segments[j - 1]["end_ms"] > max_gap_ms:
                break                                          # no unir líneas de escenas distintas
            text = " ".join(s["text"] for s in segments[i:j + 1])
            norm = normalize(text)
            out.append((i, j, norm, set(tokens(text)) or set(norm.split())))
    return out


def _best_window(probe: str, windows: list[tuple[int, int, str, set]],
                 lo: int = 0, hi: int | None = None) -> tuple[float, int, int]:
    """(score, i, j) de la mejor ventana para `probe` (exacta → difusa con prefiltro)."""
    p_norm = normalize(probe)
    p_tok = set(tokens(probe)) or set(p_norm.split())
    best = (0.0, -1, -1)
    for i, j, w_norm, w_tok in windows:
        if i < lo or (hi is not None and j >= hi):
            continue
        if p_norm and p_norm in w_norm:
            return 1.0, i, j
        if len(p_tok & w_tok) < 0.5 * len(p_tok) or len(w_norm) < 0.6 * len(p_norm):
            continue                                           # sin tokens en común / muy corta
        sc = round(fuzzy_ratio(p_norm, w_norm), 3)
        # Desempate: a igual puntaje gana la ventana más ajustada (partial_ratio da el
        # mismo valor a "línea anterior + cita" que a la cita sola).
        if sc > best[0] or (sc == best[0] and best[1] >= 0 and (j - i) < (best[2] - best[1])):
            best = (sc, i, j)
    return best


def match_quotes(quotes: list[dict], segments: list[dict], *,
                 threshold: float = QUOTE_THRESHOLD) -> list[dict]:
    """Ubica cada cita en la transcripción. Devuelve [{text, speaker, start_ms, end_ms, score}]."""
    segs = sorted(segments, key=lambda s: s["start_ms"])
    windows = build_windows(segs)
    out = []
    for q in quotes:
        words = q["text"].split()
        if len(tokens(q["text"])) < 2:
            continue
        if len(words) > 40:                                    # monólogo: anclar inicio y final
            s1, i1, _ = _best_window(" ".join(words[:18]), windows)
            if s1 < threshold:
                continue
            s2, _, j2 = _best_window(" ".join(words[-18:]), windows, lo=i1, hi=i1 + 60)
            j = j2 if s2 >= threshold else min(len(segs) - 1, i1 + 2)
            score, i = (s1 + max(s2, threshold)) / 2, i1
        else:
            score, i, j = _best_window(q["text"], windows)
            if score < threshold:
                continue
        out.append({"text": q["text"], "speaker": q.get("speaker"), "score": round(score, 3),
                    "start_ms": segs[i]["start_ms"], "end_ms": segs[j]["end_ms"]})
    return out


# ── trama ↔ transcripción ───────────────────────────────────────────


def transcript_windows(segments: list[dict], duration_ms: int, *, window_ms: int = 60_000,
                       step_ms: int = 30_000) -> list[dict]:
    wins, t = [], 0
    while t < max(duration_ms, 1):
        text = " ".join(s["text"] for s in segments if s["start_ms"] < t + window_ms and s["end_ms"] > t)
        wins.append({"start_ms": t, "end_ms": min(duration_ms, t + window_ms), "text": text})
        t += step_ms
    return wins


def align_plot(sentences: list[str], segments: list[dict], duration_ms: int, *,
               position_weight: float = 0.15) -> list[dict]:
    """Asigna cada frase de la trama a una ventana, en orden (DP monótona)."""
    if not sentences or not segments:
        return []
    wins = transcript_windows(segments, duration_ms)
    tf = Tfidf([w["text"] for w in wins] + sentences)
    sim = cosine_matrix(tf.transform(sentences), tf.transform([w["text"] for w in wins]))
    n, m = sim.shape
    sent_pos = np.linspace(0, 1, n) if n > 1 else np.array([0.5])
    win_pos = np.array([((w["start_ms"] + w["end_ms"]) / 2) / max(1, duration_ms) for w in wins])
    gain = sim - position_weight * np.abs(sent_pos[:, None] - win_pos[None, :])
    dp = np.full((n, m), -np.inf, dtype=np.float32)
    back = np.zeros((n, m), dtype=np.int32)
    dp[0] = gain[0]
    for i in range(1, n):
        run_max, run_arg = -np.inf, 0
        for j in range(m):
            if dp[i - 1, j] > run_max:
                run_max, run_arg = dp[i - 1, j], j
            dp[i, j] = run_max + gain[i, j]
            back[i, j] = run_arg
    j = int(np.argmax(dp[-1]))
    path = [0] * n
    for i in range(n - 1, -1, -1):
        path[i] = j
        j = int(back[i, j])
    return [{"sentence": sentences[i], "start_ms": wins[path[i]]["start_ms"],
             "end_ms": wins[path[i]]["end_ms"], "score": round(float(sim[i, path[i]]), 4)}
            for i in range(n)]
