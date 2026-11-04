"""Texto: normalización, similitud difusa y TF-IDF en numpy (sin sklearn)."""
from __future__ import annotations

import difflib
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Sequence

import numpy as np

STOPWORDS = frozenset("""
a about after again all am an and any are as at be because been before being but by can could
did do does doing don down during each few for from further had has have having he her here hers
him his how i if in into is it its just me more most my no nor not now of off on once only or
other our out over own same she should so some such than that the their them then there these
they this those through to too under until up very was we were what when where which while who
whom why will with would you your yeah oh hey okay ok well gonna wanna got get let us
el la los las un una unos unas y o pero si no que de del al a en con por para es son fue era
ser estar está están esto eso este esta ese esa lo le les se me te nos mi tu su sus mis tus ya
muy más como cuando donde qué quién cómo hay he ha han yo tú él ella ellos ellas usted ustedes
""".split())

_TOKEN_RE = re.compile(r"[a-z0-9ñ']+")


def normalize(text: str) -> str:
    """minúsculas, sin acentos (salvo ñ), sin puntuación, espacios simples."""
    text = (text or "").lower().replace("ñ", "\0")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c)).replace("\0", "ñ")
    text = re.sub(r"[^a-z0-9ñ' ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokens(text: str, *, drop_stopwords: bool = True) -> list[str]:
    toks = _TOKEN_RE.findall(normalize(text))
    return [t for t in toks if len(t) > 2 and (not drop_stopwords or t not in STOPWORDS)]


def fuzzy_ratio(a: str, b: str) -> float:
    """partial_ratio 0-1 (rapidfuzz si está; difflib si no)."""
    a, b = normalize(a), normalize(b)
    if not a or not b:
        return 0.0
    try:
        from rapidfuzz import fuzz  # type: ignore
        return fuzz.partial_ratio(a, b) / 100.0
    except ImportError:
        short, long_ = sorted((a, b), key=len)
        best = 0.0
        for i in range(0, max(1, len(long_) - len(short) + 1), max(1, len(short) // 4)):
            best = max(best, difflib.SequenceMatcher(None, short, long_[i:i + len(short)]).ratio())
        return best


class Tfidf:
    """TF-IDF con log-tf y normalización L2. Interpretable y sin dependencias."""

    def __init__(self, docs: Sequence[str]):
        toks = [tokens(d) for d in docs]
        df = Counter(t for ts in toks for t in set(ts))
        self.vocab = {t: i for i, t in enumerate(sorted(df))}
        n = max(1, len(docs))
        self.idf = np.array([math.log((1 + n) / (1 + df[t])) + 1.0 for t in sorted(df)], dtype=np.float32)
        self.matrix = self.transform_tokens(toks)

    def transform_tokens(self, toks: list[list[str]]) -> np.ndarray:
        m = np.zeros((len(toks), len(self.vocab)), dtype=np.float32)
        for r, ts in enumerate(toks):
            for t, c in Counter(ts).items():
                j = self.vocab.get(t)
                if j is not None:
                    m[r, j] = (1.0 + math.log(c)) * self.idf[j]
        norms = np.linalg.norm(m, axis=1, keepdims=True)
        return m / np.where(norms == 0, 1, norms)

    def transform(self, docs: Sequence[str]) -> np.ndarray:
        return self.transform_tokens([tokens(d) for d in docs])


def cosine_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Filas ya normalizadas L2 → producto punto = coseno."""
    if a.size == 0 or b.size == 0:
        return np.zeros((a.shape[0], b.shape[0]), dtype=np.float32)
    return a @ b.T
