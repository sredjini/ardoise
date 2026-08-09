"""
config.py — Configuration centralisée, lue depuis l'environnement (.env).

On ne code JAMAIS une clé en dur. Les secrets vivent dans .env (gitignoré).
"""

import os
from dotenv import load_dotenv

load_dotenv()  # charge server/.env s'il existe


class Settings:
    # LLM souverain : Scaleway (hébergé en France/EU), API compatible OpenAI.
    SCW_API_KEY: str = os.getenv("SCW_API_KEY", "")
    SCW_URL: str = os.getenv("SCW_URL", "https://api.scaleway.ai/v1")
    SCW_MODEL: str = os.getenv("SCW_MODEL", "mistral-small-3.2-24b-instruct-2506")
    # Modèle vision pour l'OCR de justificatif. mistral-small-3.2 est déjà
    # multimodal → par défaut on réutilise le même modèle.
    SCW_VISION_MODEL: str = os.getenv("SCW_VISION_MODEL", SCW_MODEL)

    # Garde-fou boucle de vérification (nombre max de corrections automatiques).
    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "2"))

    # CORS : origines autorisées, séparées par des virgules.
    # Démo public sans cookies → "*" par défaut ; en prod on restreindrait.
    ALLOW_ORIGINS: list[str] = [
        o.strip() for o in os.getenv("ALLOW_ORIGINS", "*").split(",") if o.strip()
    ]


settings = Settings()
