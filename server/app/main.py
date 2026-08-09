"""
main.py — L'API HTTP. Deux routes utiles : POST /ocr et POST /process.

Protections :
  - rate limiting par IP (slowapi) — évite l'abus / l'emballement de coûts LLM ;
  - validation d'entrée (longueur du texte, taille et type de l'image) ;
  - garde-fou métier : une entrée qui n'est pas une dépense est rejetée
    proprement (statut "rejected"), sans rien fabriquer.
Au démarrage, on pré-charge le modèle d'embeddings pour que la 1re requête
ne paie pas le coût de chargement.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from .config import settings
from .schemas import GraphState, PipelineResult
from .graph import compiled_graph
from .llm import ocr_expense
from .rag import get_referential


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Pré-chauffe : charge le modèle d'embeddings au démarrage (pas au 1er appel).
    get_referential()
    yield


limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
app = FastAPI(title="Ardoise — notes de frais agentiques", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOW_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Entrées validées -------------------------------------------------------
class ProcessIn(BaseModel):
    # Bornes : ni vide, ni un pavé abusif (protège coûts LLM et abus).
    transcript: str = Field(min_length=1, max_length=2000)

    @field_validator("transcript")
    @classmethod
    def _clean(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("transcript vide")
        return v


class OcrIn(BaseModel):
    # ~8 Mo de base64 ≈ image de ~6 Mo max.
    image: str = Field(min_length=1, max_length=8_000_000)

    @field_validator("image")
    @classmethod
    def _is_image_data_url(cls, v: str) -> str:
        if not v.startswith("data:image/"):
            raise ValueError("image doit être une data URL d'image")
        return v


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": settings.SCW_MODEL}


@app.post("/ocr")
@limiter.limit("15/minute")
def ocr(request: Request, body: OcrIn) -> dict:
    """Étape OCR : une photo de justificatif → une dictée équivalente.
    Le front enchaîne ensuite avec /process (le même cycle d'agents)."""
    return {"transcript": ocr_expense(body.image)}


@app.post("/process", response_model=PipelineResult)
@limiter.limit("20/minute")
def process(request: Request, body: ProcessIn) -> PipelineResult:
    # On lance le graphe avec l'état initial (juste le transcript).
    final = compiled_graph.invoke(GraphState(transcript=body.transcript))

    extraction = final.get("extraction")
    verification = final.get("verification")

    # Ordre des décisions : rejet d'abord (entrée non exploitable), puis statut.
    if extraction is not None and not extraction.est_une_depense:
        status = "rejected"
    elif verification is not None and verification.ok:
        status = "validated"
    elif verification is not None and verification.needs_human:
        status = "needs_human"
    else:
        status = "failed"

    return PipelineResult(
        transcript=body.transcript,
        extraction=extraction,
        coding=final.get("coding"),
        ecriture=final.get("ecriture"),
        verification=verification,
        retrieved=final.get("retrieved", []),
        retries=final.get("retries", 0),
        status=status,
    )
