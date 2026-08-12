# Ardoise — dictée comptable agentique

[![CI](https://github.com/sredjini/ardoise/actions/workflows/ci.yml/badge.svg)](https://github.com/sredjini/ardoise/actions/workflows/ci.yml)

> Dictez, photographiez ou tapez une dépense. Un pipeline de 4 agents l'**extrait**,
> la **code** (compte PCG), **rédige** l'écriture comptable et la **vérifie** —
> avec traçabilité, garde-fous et validation humaine.

Ardoise transforme une dépense exprimée en langage naturel — *« taxi gare-hôtel 34 €,
déplacement client Lyon »*, ou une **photo de ticket de caisse** — en une **écriture
comptable structurée, codée et contrôlée**, prête à être validée par un comptable.

---

## Le besoin

Saisir des notes de frais coûte du temps : retrouver le bon **compte du Plan Comptable
Général**, appliquer le **bon taux de TVA**, vérifier la cohérence des montants. C'est
répétitif, à faible valeur, et source d'erreurs. Le collaborateur veut juste dire (ou
prendre en photo) ce qu'il a payé — depuis son téléphone, dans le taxi.

## La solution

Une **web app multi-modale** : 3 entrées (voix / photo / texte), **un seul cycle
d'agents**. L'humain valide. Chaque décision est **tracée** (d'où vient le compte, avec
quelle confiance) — parce qu'en comptabilité on ne fait pas confiance à une IA à l'aveugle.

---

## Architecture

```
🎙️ voix (Web Speech)     📷 photo (OCR vision EU)     ⌨️ texte
        └──────────────────────┬──────────────────────┘
                               ▼ transcript
┌──────────────────────────────────────────────────────────────┐
│  Pipeline d'agents (LangGraph)                                │
│                                                              │
│  [si non-dépense → REJET propre, rien n'est fabriqué]        │
│  1. EXTRACTION   → {marchand, motif, date, montant}  (LLM)   │
│  2. CODAGE       → compte PCG via RAG sur référentiel (LLM)  │
│  3. RÉDACTION    → écriture comptable  (déterministe, Python)│
│  4. VÉRIFICATION → contrôle + ancrage  (LLM indépendant)     │
│                         │                                    │
│         ┌───────────────┴───────────────┐                    │
│         ▼ ok                 ▼ corrigeable                   │
│      validé            reboucle (max N)  ─────► extraction   │
│                         ▼ ambigu                             │
│                    escalade humaine                          │
└──────────────────────────────────────────────────────────────┘
        │
        ▼
UI React : la chaîne d'agents, la confiance, la traçabilité, le verdict
```

## Les choix de conception (et pourquoi)

- **Multi-modal, un seul cycle.** Voix, photo (OCR) et texte produisent tous le même
  `transcript` qui alimente le même graphe. L'OCR est une simple *étape d'entrée*
  supplémentaire, pas un pipeline parallèle.

- **Structured output partout.** Chaque agent remplit un schéma Pydantic typé — pas de
  texte libre à parser. La structure est garantie ; le LLM « réfléchit dans les cases ».

- **Agentique là où ça le mérite, pas partout.** Le happy-path est une chaîne. Ce qui en
  fait un *système* : la **boucle de vérification** (un agent indépendant peut renvoyer
  corriger), le **tool use** (le codage interroge un RAG), et l'**aiguillage** (rejet des
  entrées non exploitables). Pas d'artillerie multi-agent pour le décor.

- **Déterministe là où l'erreur coûte cher.** Les **montants HT/TVA sont calculés en
  Python**, jamais générés par le LLM. Le **taux de TVA vient du référentiel**, pas du
  modèle — il ne peut pas l'inventer.

- **RAG pour une raison, pas pour la frime.** Avec 10 comptes on pourrait tout mettre dans
  le prompt. On fait du retrieval parce qu'un **vrai plan de comptes fait des milliers de
  lignes** et ne tiendrait pas en contexte — archi réaliste, et le choix de compte devient
  une étape isolée et testable.

- **Garde-fous.** Entrée non-dépense → **rejet** (`est_une_depense=false`), sans rien
  fabriquer. Longueur du texte bornée, type d'image validé, **rate limiting par IP**.

- **L'humain garde la main.** Un champ essentiel manquant (montant) → **escalade humaine**.

- **Souveraineté.** LLM et OCR hébergés en **Europe (Scaleway)** — la donnée ne part pas
  hors UE. En prod, la STT navigateur serait remplacée par un moteur EU derrière la même
  interface `Transcriber`.

## Stack

| Couche          | Techno                                                              |
|-----------------|---------------------------------------------------------------------|
| Front           | React + TypeScript + Vite                                           |
| Entrées         | Web Speech API (voix), upload image (photo), texte                 |
| Orchestration   | **LangGraph** (graphe à état, aiguillage + boucle conditionnelle)  |
| LLM / OCR       | Scaleway (EU) — `langchain-openai`, mistral-small (multimodal)     |
| Structured out. | Pydantic (`with_structured_output`)                                |
| Retrieval       | `fastembed` (MiniLM multilingue 384d), cosinus en mémoire          |
| API             | FastAPI + `slowapi` (rate limit)                                   |

## Lancer en local

**Backend** (Python 3.13, [uv](https://docs.astral.sh/uv/))
```bash
cd server
cp .env.example .env      # renseigner SCW_API_KEY / SCW_URL
uv sync
uv run uvicorn app.main:app --port 8000
```

**Front**
```bash
cd web
npm install
npm run dev               # http://localhost:5173
```

Ouvrir dans **Chrome** (Web Speech API), puis dicter, coller une photo de ticket, ou
utiliser le bouton « ticket de caisse (exemple) ».

## Déployer sur Render

Le blueprint [render.yaml](render.yaml) crée deux services :

- `sredjini-ardoise-api` : API FastAPI en Docker, région Frankfurt, health check `/health`.
- `sredjini-ardoise` : site statique Vite, build `npm ci && npm run build`, publish `dist`.

Au premier déploiement Render, renseigner les secrets demandés :

```bash
SCW_URL=https://api.scaleway.ai/<project-id>/v1
SCW_API_KEY=<secret>
```

Les URLs sont câblées par défaut :

```bash
VITE_API_URL=https://sredjini-ardoise-api.onrender.com
ALLOW_ORIGINS=https://sredjini-ardoise.onrender.com
```

## Structure

```
scribe-med/
├── web/                  front React/TS
│   └── src/
│       ├── App.tsx       orchestration + chaîne visuelle + pipeline
│       └── lib/          transcriber (voix) · api · types
├── server/               backend Python
│   ├── app/
│   │   ├── schemas.py    contrats typés (structured output) + état du graphe
│   │   ├── llm.py        client LLM EU + OCR vision
│   │   ├── rag.py        retrieval en mémoire sur le référentiel PCG
│   │   ├── agents.py     les 4 nœuds (dont rédaction déterministe)
│   │   ├── graph.py      le graphe LangGraph (aiguillage + boucle)
│   │   └── main.py       API FastAPI + garde-fous
│   └── data/pcg.json     référentiel de comptes (extrait du PCG)
└── cours/                notes techniques (choix, lecture du code)
```

## Feuille de route

- OCR multi-formats (v1 = un justificatif type) et STT pro en streaming, derrière les
  interfaces existantes.
- Vrai plan de comptes + comptes analytiques (là où la RAG prend tout son sens).
- Tests automatisés (calcul TVA, aiguillage rejet).
- Ambient : capter une conversation à 2 voix plutôt qu'une dictée mono-locuteur.
- Export vers un logiciel comptable (FEC).
