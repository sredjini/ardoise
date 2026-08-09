"""Retrieval en mémoire sur le référentiel PCG.

Deux backends sont disponibles :
  - lexical, par défaut pour la démo Render 512 MiB ;
  - fastembed, plus proche d'un retrieval embeddings, activable avec
    RAG_BACKEND=fastembed quand la mémoire disponible le permet.
"""

import json
import math
import os
import re
import unicodedata
from collections import Counter
from pathlib import Path

_DATA = Path(__file__).resolve().parent.parent / "data" / "pcg.json"
_STOPWORDS = {
    "a",
    "au",
    "aux",
    "avec",
    "d",
    "de",
    "des",
    "du",
    "en",
    "et",
    "j",
    "l",
    "la",
    "le",
    "les",
    "pour",
    "un",
    "une",
}


def _tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return [tok for tok in re.findall(r"[a-z0-9]+", text) if tok not in _STOPWORDS]


class LexicalReferential:
    """Scorer lexical léger pour la démo hébergée."""

    def __init__(self) -> None:
        self.entries: list[dict] = json.loads(_DATA.read_text(encoding="utf-8"))
        self._vectors = [
            Counter(_tokens(f"{e['compte']} {e['libelle']} {e['exemples']} {e.get('regle', '')}"))
            for e in self.entries
        ]

    @staticmethod
    def _cosine(a: Counter[str], b: Counter[str]) -> float:
        dot = sum(weight * b.get(tok, 0) for tok, weight in a.items())
        norm_a = math.sqrt(sum(weight * weight for weight in a.values()))
        norm_b = math.sqrt(sum(weight * weight for weight in b.values()))
        return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0

    def retrieve(self, query: str, k: int = 4) -> list[dict]:
        q = Counter(_tokens(query))
        ranked = sorted(
            enumerate(self._vectors),
            key=lambda item: self._cosine(q, item[1]),
            reverse=True,
        )[:k]

        results = []
        for i, vector in ranked:
            entry = dict(self.entries[i])
            entry["score"] = round(self._cosine(q, vector), 3)
            entry["retrieval_backend"] = "lexical"
            results.append(entry)
        return results


class FastEmbedReferential:
    """Backend embeddings optionnel, gardé pour une infra avec plus de mémoire."""

    def __init__(self) -> None:
        import numpy as np
        from fastembed import TextEmbedding

        self._np = np
        self.entries: list[dict] = json.loads(_DATA.read_text(encoding="utf-8"))
        self._model = TextEmbedding(
            model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        )
        passages = [f"{e['libelle']}. {e['exemples']}" for e in self.entries]
        vecs = np.array(list(self._model.embed(passages)), dtype=np.float32)
        self._matrix = self._normalize(vecs)

    def _normalize(self, v):
        norms = self._np.linalg.norm(v, axis=-1, keepdims=True)
        return v / self._np.clip(norms, 1e-9, None)

    def retrieve(self, query: str, k: int = 4) -> list[dict]:
        q = self._np.array(list(self._model.embed([query]))[0], dtype=self._np.float32)
        q = self._normalize(q[None, :])[0]
        scores = self._matrix @ q
        top = self._np.argsort(-scores)[:k]

        results = []
        for i in top:
            entry = dict(self.entries[int(i)])
            entry["score"] = round(float(scores[i]), 3)
            entry["retrieval_backend"] = "fastembed"
            results.append(entry)
        return results


_referential: LexicalReferential | FastEmbedReferential | None = None


def get_referential() -> LexicalReferential | FastEmbedReferential:
    global _referential
    if _referential is None:
        backend = os.getenv("RAG_BACKEND", "lexical").lower()
        _referential = FastEmbedReferential() if backend == "fastembed" else LexicalReferential()
    return _referential
