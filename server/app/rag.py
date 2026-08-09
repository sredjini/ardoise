"""
rag.py — Retrieval en mémoire sur le référentiel PCG.

Pourquoi RAG et pas tout mettre dans le prompt ? Pour 40 comptes on POURRAIT
inliner. On fait du retrieval parce qu'un vrai plan de comptes fait des
centaines/milliers de lignes (+ comptes analytiques) → ça ne tiendrait plus
en contexte. C'est l'archi réaliste, et ça isole le "choix de compte" comme
une étape testable.

Modèle : paraphrase-multilingual-MiniLM-L12-v2 (384d) — léger, multilingue,
bon en français. (Pas de préfixe "query:/passage:" ici : ça, c'était spécifique
à la famille E5.)
"""

import json
from pathlib import Path

import numpy as np
from fastembed import TextEmbedding

_DATA = Path(__file__).resolve().parent.parent / "data" / "pcg.json"


class Referential:
    """Charge le référentiel, l'encode une fois, et répond aux requêtes."""

    def __init__(self) -> None:
        self.entries: list[dict] = json.loads(_DATA.read_text(encoding="utf-8"))
        self._model = TextEmbedding(
            model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        )

        # Texte encodé par entrée : libellé + exemples (ce sur quoi on matche).
        passages = [f"{e['libelle']}. {e['exemples']}" for e in self.entries]
        # matrice (N, 384), normalisée pour que le produit scalaire = cosinus.
        vecs = np.array(list(self._model.embed(passages)), dtype=np.float32)
        self._matrix = self._normalize(vecs)

    @staticmethod
    def _normalize(v: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(v, axis=-1, keepdims=True)
        return v / np.clip(norms, 1e-9, None)

    def retrieve(self, query: str, k: int = 4) -> list[dict]:
        """Renvoie les k comptes les plus proches, avec leur score de similarité."""
        q = np.array(list(self._model.embed([query]))[0], dtype=np.float32)
        q = self._normalize(q[None, :])[0]
        scores = self._matrix @ q                       # cosinus (N,)
        top = np.argsort(-scores)[:k]
        out = []
        for i in top:
            entry = dict(self.entries[int(i)])
            entry["score"] = round(float(scores[i]), 3)
            out.append(entry)
        return out


# Singleton : on encode le référentiel UNE fois au démarrage (coûteux), pas
# à chaque requête.
_referential: Referential | None = None


def get_referential() -> Referential:
    global _referential
    if _referential is None:
        _referential = Referential()
    return _referential
