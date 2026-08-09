"""
llm.py — Fabrique du modèle de langage (Scaleway EU) + structured output.

On expose UN helper : `structured(SchemaClass)` renvoie un "runnable" qui,
appelé avec un prompt, renvoie DIRECTEMENT une instance Pydantic validée.
C'est LangChain qui force le LLM à remplir le schéma (function calling / json
schema) et qui relance si la sortie ne colle pas.
"""

from functools import lru_cache
from typing import Type, TypeVar

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from .config import settings

T = TypeVar("T", bound=BaseModel)


@lru_cache(maxsize=1)
def _base_llm() -> ChatOpenAI:
    """Le client LLM, créé une seule fois (température basse = déterministe)."""
    return ChatOpenAI(
        model=settings.SCW_MODEL,
        api_key=settings.SCW_API_KEY,
        base_url=settings.SCW_URL,
        temperature=0,  # comptabilité = on veut de la reproductibilité, pas de créativité
        timeout=60,
    )


def structured(schema: Type[T]):
    """Renvoie un runnable LLM qui produit une instance validée de `schema`."""
    return _base_llm().with_structured_output(schema)


@lru_cache(maxsize=1)
def _vision_llm() -> ChatOpenAI:
    """Modèle vision pour l'OCR de justificatif (mistral-small est multimodal)."""
    return ChatOpenAI(
        model=settings.SCW_VISION_MODEL,
        api_key=settings.SCW_API_KEY,
        base_url=settings.SCW_URL,
        temperature=0,
        timeout=90,
    )


# Prompt OCR : on ne veut PAS un dump brut, mais la dépense résumée comme une
# dictée — pour qu'elle entre dans le MÊME cycle d'agents que la voix.
_OCR_PROMPT = (
    "Cette image est un justificatif de dépense (ticket de caisse, reçu, facture). "
    "Lis-le et résume la dépense en UNE phrase française, comme si un salarié la "
    "dictait pour sa note de frais : nature ou marchand, montant TTC en euros, et "
    "la date si elle est lisible. N'invente aucune information absente."
)


def ocr_expense(image_data_url: str) -> str:
    """OCR d'un justificatif → une 'dictée équivalente' qui alimente le cycle."""
    msg = HumanMessage(
        content=[
            {"type": "text", "text": _OCR_PROMPT},
            {"type": "image_url", "image_url": {"url": image_data_url}},
        ]
    )
    result = _vision_llm().invoke([msg])
    return str(result.content).strip()
