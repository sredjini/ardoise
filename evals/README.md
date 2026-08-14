# Ardoise — Durcissement production : Évaluation & Observabilité

> **Brief d'implémentation pour un agent de code (Codex).**
> Objectif : faire passer Ardoise de « ça marche » à « c'est **mesuré, observable et
> maîtrisé en coût** ». Cette partie ne change pas le produit ; elle **prouve avec des
> chiffres** la rigueur du pipeline (le fil rouge d'Ardoise).

---

## 0. But & non-buts

**But.** Ajouter trois choses à Ardoise, sans réécrire le pipeline :
1. **Observabilité** — tracer chaque appel LLM et chaque exécution du graphe (tokens, coût €, latence, statut).
2. **Évaluation** — un jeu de test « golden » + des métriques + un runner reproductible.
3. **Garde-fou CI** — un gate qui échoue sur régression de qualité avant merge.

**Non-buts (ne PAS faire).**
- Pas d'entraînement / fine-tuning de modèle.
- Pas de nouvelle infra lourde (pas de K8s, pas de cluster).
- Ne pas casser les principes existants : **déterministe sur l'argent**, LLM EU souverain (Scaleway), agent de vérification indépendant.
- Ne pas committer de secret (tout en `.env`).

---

## 1. Contexte technique (l'existant — ne pas re-découvrir)

Stack : **FastAPI + LangGraph**, 4 agents, RAG en mémoire (`fastembed`) sur un plan comptable, **LLM EU Scaleway** (API compatible OpenAI) via `langchain-openai`. Python 3.13, gestion des deps avec **uv**.

Fichiers clés (`server/app/`) :

| Fichier | Rôle |
|---|---|
| `main.py` | API FastAPI. Routes `POST /process`, `POST /ocr`, `GET /health`. Rate-limit slowapi, CORS, lifespan (pré-chauffe embeddings). Le graphe est invoqué par `compiled_graph.invoke(GraphState(transcript=...))`. |
| `graph.py` | `build_graph()` / `compiled_graph` : StateGraph, arêtes conditionnelles, boucle de vérif (`MAX_RETRIES`). |
| `agents.py` | Les 4 nœuds : `extract_node`, `code_node` (RAG), `draft_node` (**pur Python**, arithmétique), `verify_node` (contrôleur indépendant + garde-fous déterministes). |
| `schemas.py` | Contrats Pydantic : `Extraction`, `CodingChoice`/`Coding`, `Ecriture`, `Issue`/`Verification`, `GraphState`, `PipelineResult`. |
| `llm.py` | `structured(Schema)` (structured output), `_base_llm()`/`_vision_llm()` (ChatOpenAI, `temperature=0`), `ocr_expense(image)`. |
| `rag.py` | `get_referential().retrieve(query, k)` sur `data/pcg.json`. |
| `config.py` | `settings` : `SCW_API_KEY`, `SCW_URL`, `SCW_MODEL`, `SCW_VISION_MODEL`, `MAX_RETRIES`, `ALLOW_ORIGINS`. |
| `data/pcg.json` | Le référentiel (comptes PCG + `tva_usuelle` + règles). |

Invariants à respecter :
- `temperature=0` partout (reproductibilité).
- `draft_node` calcule HT/TVA en Python ; le taux vient du justificatif s'il est présent (`extraction.tva_taux`), sinon du référentiel.
- `verify_node` est un LLM **séparé** + garde-fous déterministes (montant manquant → `needs_human` ; taux reçu ≠ taux compte → avertissement).

---

## 2. Architecture cible (3 étages + observabilité transverse)

```
                ┌──────────────────────────────────────────────┐
                │  ÉTAGE 3 — OBSERVABILITÉ PROD (Langfuse)      │
                │  chaque appel LLM + run graphe : tokens,      │
                │  coût €, latence p50/p95, statut, trace       │
                └──────────────────────────────────────────────┘
   ┌───────────────────────┐        ┌───────────────────────────┐
   │ ÉTAGE 1 — OFFLINE      │        │ ÉTAGE 2 — CI GATE          │
   │ golden dataset +       │  ───►  │ GitHub Actions : rejoue    │
   │ metrics + runner       │        │ les evals sur PR, bloque   │
   │ (reproductible, local) │        │ si régression vs baseline  │
   └───────────────────────┘        └───────────────────────────┘
```

Transverse : **coût & latence** (angle FinOps — c'est le différenciateur, à soigner).

---

## 3. Découpage en tâches (ordre imposé, avec critères d'acceptation)

> Chaque tâche : *fichiers*, *quoi faire*, *definition of done (DoD)*. Livre par petits commits.

### Phase A — Observabilité (Langfuse) — **fais ça en premier**
- **Fichiers** : `server/app/observability.py` (nouveau), branchements dans `llm.py` / `main.py` ; `server/.env.example`.
- **Quoi** :
  - Intégrer **Langfuse** via le callback handler LangChain (les LLM sont des `ChatOpenAI` LangChain → le `CallbackHandler` capture tokens/latence automatiquement).
  - Passer le handler à `.invoke(..., config={"callbacks": [handler]})` dans `code/extract/verify` **ou** au niveau du graphe dans `main.py` (`compiled_graph.invoke(state, config={"callbacks":[handler], "run_name":"ardoise"})`). Préférer le niveau graphe : une seule trace par requête, avec les 4 nœuds en spans.
  - Config par env : `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` (région EU ou self-host). Si absents → **no-op** (l'app tourne sans Langfuse, jamais de crash).
  - Renseigner le **coût** : mapper le prix du modèle Scaleway (tokens in/out) dans Langfuse (model pricing) pour avoir des € par trace.
- **DoD** : lancer `/process` une fois → une trace apparaît dans Langfuse avec les 4 spans (extract→code→draft→verify), tokens, latence, et un coût € non nul. Sans clés Langfuse, l'app fonctionne à l'identique.
- **Docs** : voir §5 « Observabilité ».

### Phase B — Golden dataset + runner
- **Fichiers** : `evals/dataset/golden.jsonl`, `evals/runner.py`, `evals/schema.py`.
- **Quoi** :
  - Schéma d'un cas (`evals/schema.py`, Pydantic) :
    ```json
    {
      "id": "repas-bistrot-01",
      "source": "texte|photo",
      "input": "Repas d'affaires au Bistrot Marceau, 82 € TTC, TVA 10%",
      "expected": {
        "est_une_depense": true,
        "compte": "6257",
        "tva_taux": 10,
        "montant_ttc": 82.0,
        "status": "validated"
      },
      "failure_mode": null
    }
    ```
  - **≥ 20 cas** couvrant les modes de défaillance (1 tag `failure_mode` par cas) :
    - nominal (taxi→6251, hôtel→6256, repas→6257, fournitures→6064…) ;
    - **montant manquant** → `status: needs_human` ;
    - **hors-sujet / charabia** → `status: rejected` ;
    - **taux atypique** (reçu à 20% sur un compte usuel 10%) → l'écriture reste juste mais `verification.issues` doit contenir un avertissement `tva_taux` ;
    - compte **ambigu** (missions vs réceptions) → vérifier que le bon est choisi.
  - `evals/runner.py` : charge le golden, appelle le pipeline (importer `compiled_graph` **ou** taper `/process` en local), collecte les sorties, calcule les métriques (Phase C), imprime un **tableau** + écrit `evals/results/latest.json`.
- **DoD** : `uv run python -m evals.runner` produit un tableau lisible (par cas + agrégé) et un JSON de résultats.

### Phase C — Métriques (adaptées à Ardoise)
- **Fichiers** : `evals/metrics.py`.
- **Quoi** (déterministes d'abord, LLM-judge ensuite en Phase D) :
  - **Retrieval** : `compte_in_candidates@k` (le bon compte est-il dans les candidats RAG ?), **MRR** du bon compte.
  - **Imputation** : exact-match du `compte` choisi vs `expected.compte` ; correctness du `tva_taux` retenu.
  - **Arithmétique** (doit toujours passer, sinon bug) : `abs(HT+TVA − TTC) < 0.01` et TVA cohérente avec le taux → assertion dure.
  - **Bout-en-bout** : exactitude du `status` (validated/needs_human/rejected) vs `expected.status`.
  - **Vérificateur** : sur les cas « cassés » (taux atypique, montant manquant), le `verify_node` lève-t-il bien l'issue attendue ? → precision/recall du détecteur.
- **DoD** : chaque métrique a un test unitaire (`evals/tests/`) sur 2-3 cas jouets.

### Phase D — LLM-as-judge calibré (optionnel mais valorisant)
- **Fichiers** : `evals/judge.py`.
- **Quoi** :
  - Un juge LLM pour la **qualité de la justification** du codage (ancrage : cite-t-il la règle du référentiel ? pas d'invention ?), scoré 1–5 avec **rubrique explicite** + **multi-pass** (3 passes, moyenne + écart-type pour la confiance).
  - **Calibration** : annoter ~15 cas à la main, viser une **corrélation de Spearman ≥ 0.8** juge vs humain ; documenter le score obtenu.
- **DoD** : `evals/judge.py` renvoie score + variance ; un petit script imprime la corrélation vs annotations.
- **Docs** : §5 « LLM-as-judge ».

### Phase E — Garde-fou CI
- **Fichiers** : `.github/workflows/evals.yml`, `evals/gate.py`.
- **Quoi** :
  - Job GitHub Actions sur PR : `uv sync` → `uv run python -m evals.runner` → `evals/gate.py` compare aux seuils (`evals/thresholds.json`, ex. `compte_accuracy ≥ 0.9`, `status_accuracy ≥ 0.9`, arithmétique = 1.0) et **échoue si régression**.
  - Les clés Scaleway/Langfuse viennent des **GitHub Secrets** ; si la CI ne doit pas dépenser de LLM, prévoir un mode « cassettes » (réponses enregistrées) — voir note VCR en §4.
  - Publier le tableau de résultats en **artifact** de la PR.
- **DoD** : une PR qui dégrade l'imputation fait **échouer** la CI ; une PR neutre passe.

### Phase F — Coût & latence exposés (angle FinOps)
- **Fichiers** : `server/app/main.py` (`GET /metrics`), `web/src/…` (petit affichage).
- **Quoi** :
  - Endpoint `GET /metrics` (Prometheus ou JSON) : coût cumulé, tokens, latence p50/p95 par route.
  - Front : afficher discrètement **coût & latence** de la dernière requête (déjà dispo via la trace / headers) — matérialise le « je sais instrumenter le coût ».
- **DoD** : après quelques requêtes, `/metrics` renvoie des chiffres cohérents ; le front montre « ~X ms · ~Y centimes ».

---

## 4. Conventions & contraintes

- **Secrets** : uniquement dans `server/.env` (gitignoré). Créer/mettre à jour `server/.env.example` avec `SCW_*` et `LANGFUSE_*` (valeurs vides). Ne **jamais** committer de clé.
- **Souveraineté** : rester EU. Langfuse = self-host (Docker) **ou** cloud région EU. Le juge/évaluateur LLM peut réutiliser le modèle Scaleway (via `_base_llm()`), pas besoin d'OpenAI.
- **Provider-agnostique** : passer par `base_url` OpenAI-compatible (déjà le cas).
- **Déterminisme** : `temperature=0` ; ne pas introduire d'aléa dans les evals (seed fixe si besoin).
- **Deps** : `uv add …` (pas de pip direct). Nouvelles deps probables : `langfuse`, et pour les métriques au choix `ragas` et/ou `deepeval` (n'en tirer que ce qui sert — ne pas importer un framework entier pour 3 métriques). `pytest` pour les tests.
- **CI sans coût** : pour éviter de brûler des tokens à chaque PR, enregistrer les réponses LLM (pattern « cassettes », p.ex. `pytest-recording`/VCR) et rejouer hors-ligne. Documenter comment ré-enregistrer.
- **Isolation** : le code d'éval vit sous `evals/` ; ne pas mélanger avec les tests unitaires du serveur.

---

## 5. Toute la doc à utiliser

**Concepts (à lire avant de coder — le *pourquoi*)**
- Hamel Husain — *Your AI product needs evals* : https://hamel.dev/blog/posts/evals/
- Hamel Husain — *Creating an LLM-as-a-judge that drives business value* : https://hamel.dev/blog/posts/llm-judge/
- Eugene Yan — *LLM evaluators (LLM-as-judge)* : https://eugeneyan.com/writing/llm-evaluators/

**Observabilité / tracing**
- Langfuse — docs : https://langfuse.com/docs
- Langfuse — intégration LangChain/LangGraph : https://langfuse.com/docs/integrations/langchain
- Langfuse — self-hosting (EU) : https://langfuse.com/self-hosting
- Langfuse — coûts / model pricing : https://langfuse.com/docs/model-usage-and-cost
- OpenTelemetry — conventions GenAI (le standard) : https://opentelemetry.io/docs/specs/semconv/gen-ai/

**Frameworks d'évaluation**
- Ragas (métriques RAG : faithfulness, context precision/recall…) : https://docs.ragas.io
- DeepEval (style pytest) : https://github.com/confident-ai/deepeval
- promptfoo (eval + gate en YAML, s'intègre en CI) : https://www.promptfoo.dev/docs/

**LLM-as-judge (théorie, pour la Phase D)**
- *Judging LLM-as-a-Judge* (MT-Bench, Zheng et al.) : https://arxiv.org/abs/2306.05685
- *G-Eval* : https://arxiv.org/abs/2303.16634

**Cadre agentique (rappel)**
- LangGraph : https://langchain-ai.github.io/langgraph/
- LangChain callbacks : https://python.langchain.com/docs/concepts/callbacks/
- (option, evals d'agents) Inspect (UK AISI) : https://inspect.aisi.org.uk/

**Handbook de référence** (blueprint, à s'inspirer, pas à copier tel quel)
- freeCodeCamp — *AI Evaluation Engineering: Build a Production-Grade LLM Evaluation Platform* (three-tier, golden datasets, LLM-as-judge, CI gate).

---

## 6. Definition of Done (global)

- [ ] Une requête `/process` produit une **trace Langfuse** complète (4 spans, tokens, coût €, latence). App fonctionnelle **sans** clés Langfuse.
- [ ] `evals/dataset/golden.jsonl` : **≥ 20 cas** couvrant tous les modes de défaillance listés.
- [ ] `uv run python -m evals.runner` : tableau de métriques + `evals/results/latest.json`.
- [ ] Métriques déterministes (imputation, arithmétique, status, détecteur de vérif) + tests unitaires.
- [ ] (option) Juge LLM calibré, corrélation Spearman documentée (viser ≥ 0.8).
- [ ] **CI** : `.github/workflows/evals.yml` rejoue les evals et **bloque sur régression** ; artifact publié.
- [ ] `/metrics` + affichage coût/latence côté front.
- [ ] `server/.env.example` à jour ; **aucun secret** committé ; ce README maintenu.

---

## 7. Ordre de démarrage conseillé

1. Lire Hamel (§5) → cadrer le *pourquoi*.
2. **Phase A** (Langfuse) — visibilité immédiate, faible risque.
3. **Phase B + C** — golden set + métriques déterministes (le cœur de la valeur).
4. **Phase E** — CI gate (verrouille les acquis).
5. **Phase D** puis **F** — juge calibré + FinOps (les différenciateurs).
