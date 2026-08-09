"""
schemas.py — Contrats typés (Pydantic) de tout le pipeline.

Chaque agent reçoit et renvoie une structure TYPÉE. C'est le "structured
output" : on ne laisse pas le LLM répondre en texte libre, on le force à
remplir un schéma. Avantages : rendu fiable côté front, pas de parsing
fragile, et le LLM "réfléchit dans les cases" qu'on lui impose.

Le `GraphState` en bas est l'état partagé qui circule de nœud en nœud dans
LangGraph : chaque agent lit ce dont il a besoin et écrit son résultat.
"""

from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field


# --- 1. EXTRACTION ----------------------------------------------------------
class Extraction(BaseModel):
    """Ce que l'agent d'extraction tire du texte dicté."""
    # Garde-fou : l'agent déclare d'abord si le texte décrit VRAIMENT une
    # dépense professionnelle. Si non (charabia, phrase hors-sujet…), on ne
    # fabrique rien : on rejette proprement.
    est_une_depense: bool = Field(
        True, description="False si le texte ne décrit pas une dépense professionnelle"
    )
    marchand: Optional[str] = Field(None, description="Commerçant / fournisseur")
    motif: Optional[str] = Field(None, description="Raison professionnelle de la dépense")
    date: Optional[str] = Field(None, description="Date de la dépense (AAAA-MM-JJ si connue)")
    montant_ttc: Optional[float] = Field(None, description="Montant total TTC en euros")
    tva_taux: Optional[float] = Field(None, description="Taux de TVA annoncé si mentionné (%)")
    # L'agent DOIT lister ce qui manque ou est ambigu : c'est ce qui déclenche
    # l'escalade vers l'humain plutôt qu'une invention.
    champs_manquants: list[str] = Field(
        default_factory=list,
        description="Champs absents ou ambigus dans la dictée (ex: 'montant', 'date')",
    )


# --- 2. CODAGE (avec RAG) ---------------------------------------------------
class CodingChoice(BaseModel):
    """Ce que le LLM décide VRAIMENT : juste le compte + son raisonnement.
    Le taux de TVA et la déductibilité, on les lit dans le référentiel (pas le
    LLM) → il ne peut pas se tromper sur une donnée qu'on possède déjà."""
    compte: str = Field(description="Numéro de compte PCG choisi parmi les candidats")
    justification: str = Field(description="Pourquoi ce compte, en citant l'exemple du référentiel")
    confidence: float = Field(ge=0, le=1, description="Confiance 0..1 dans le choix")


class Coding(BaseModel):
    """Le compte comptable choisi par l'agent de codage."""
    compte: str = Field(description="Numéro de compte PCG choisi (ex: 6251)")
    libelle: str = Field(description="Libellé du compte")
    tva_taux: float = Field(description="Taux de TVA retenu (%)")
    deductible: bool = Field(description="TVA déductible ou non")
    justification: str = Field(description="Pourquoi ce compte, en citant l'exemple du référentiel")
    confidence: float = Field(ge=0, le=1, description="Confiance 0..1 dans le choix")


# --- 3. RÉDACTION (écriture comptable) --------------------------------------
class Ecriture(BaseModel):
    """L'écriture comptable pré-rédigée, prête à être postée après validation."""
    compte_charge: str = Field(description="Compte de charge au débit (ex: 6251)")
    montant_ht: float = Field(description="Montant HT")
    compte_tva: str = Field(default="44566", description="Compte de TVA déductible")
    montant_tva: float = Field(description="Montant de TVA")
    montant_ttc: float = Field(description="Montant TTC")
    libelle_ecriture: str = Field(description="Libellé lisible de l'écriture")


# --- 4. VÉRIFICATION (agent indépendant) ------------------------------------
class Issue(BaseModel):
    champ: str = Field(description="Champ concerné par le problème")
    probleme: str = Field(description="Description du problème détecté")
    severite: Literal["bloquant", "avertissement"] = "avertissement"


class Verification(BaseModel):
    """Verdict de l'agent de contrôle. C'est lui qui décide de la boucle."""
    ok: bool = Field(description="True si l'écriture est cohérente et fondée")
    issues: list[Issue] = Field(default_factory=list)
    # Si l'agent estime qu'un humain doit trancher (ambiguïté irréductible),
    # on n'insiste pas en boucle : on escalade.
    needs_human: bool = Field(default=False, description="Escalade à un validateur humain")
    correction_hint: Optional[str] = Field(
        None, description="Indice pour corriger si on repasse en extraction/codage"
    )


# --- État partagé du graphe -------------------------------------------------
class GraphState(BaseModel):
    """
    L'état qui circule dans le graphe LangGraph. Chaque nœud le lit et le
    complète. `retries` compte les passages dans la boucle de vérif (garde-fou
    pour ne pas boucler à l'infini).
    """
    transcript: str                                  # entrée : texte dicté
    extraction: Optional[Extraction] = None
    coding: Optional[Coding] = None
    ecriture: Optional[Ecriture] = None
    verification: Optional[Verification] = None
    retries: int = 0
    # Contexte RAG récupéré (pour la traçabilité côté front)
    retrieved: list[dict] = Field(default_factory=list)


# --- Réponse API ------------------------------------------------------------
class PipelineResult(BaseModel):
    """Ce que l'API renvoie au front : tout, pour la traçabilité."""
    transcript: str
    extraction: Optional[Extraction] = None
    coding: Optional[Coding] = None
    ecriture: Optional[Ecriture] = None
    verification: Optional[Verification] = None
    retrieved: list[dict] = Field(default_factory=list)
    retries: int = 0
    status: Literal["validated", "needs_human", "rejected", "failed"] = "validated"
