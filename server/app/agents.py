"""
agents.py — Les nœuds du graphe. Chaque fonction prend l'état et renvoie les
champs à mettre à jour (convention LangGraph).

Répartition volontaire :
  - EXTRACTION, CODAGE, VÉRIF  → agents LLM (compréhension, jugement).
  - RÉDACTION                  → déterministe (arithmétique sur l'argent :
                                 JAMAIS un LLM. On calcule, on n'invente pas).
"""

from .schemas import GraphState, Extraction, Coding, CodingChoice, Ecriture, Verification, Issue
from .llm import structured
from .rag import get_referential


# --- Nœud 1 : EXTRACTION ----------------------------------------------------
def extract_node(state: GraphState) -> dict:
    hint = ""
    if state.verification and state.verification.correction_hint:
        # On repasse ici via la boucle : on injecte l'indice de correction.
        hint = f"\n\nCorrige en tenant compte de : {state.verification.correction_hint}"

    prompt = (
        "Tu extrais les informations d'une note de frais dictée par un salarié.\n"
        "D'ABORD, juge si le texte décrit vraiment une DÉPENSE professionnelle. "
        "Si c'est du charabia, une phrase hors-sujet ou rien d'exploitable, mets "
        "`est_une_depense` à false et laisse les autres champs vides.\n"
        "Sinon, ne DEVINE jamais un montant ou une date absents : liste-les dans "
        "`champs_manquants`.\n\n"
        f"Dictée : « {state.transcript} »{hint}"
    )
    result: Extraction = structured(Extraction).invoke(prompt)
    return {"extraction": result}


# --- Nœud 2 : CODAGE (avec RAG) --------------------------------------------
def code_node(state: GraphState) -> dict:
    ex = state.extraction
    # Requête de retrieval : ce qui décrit la nature de la dépense.
    query = " ".join(filter(None, [ex.marchand, ex.motif])) or state.transcript
    candidates = get_referential().retrieve(query, k=4)

    # On présente les candidats au LLM et on le force à CHOISIR parmi eux
    # (il ne peut pas inventer un compte hors référentiel).
    lignes = "\n".join(
        f"- {c['compte']} {c['libelle']} — ex: {c['exemples']} "
        f"(TVA {c['tva_usuelle']}%, déductible={c['deductible']}; {c.get('regle','')})"
        for c in candidates
    )
    prompt = (
        "Tu es comptable. Choisis LE compte du Plan Comptable Général le plus "
        "SPÉCIFIQUE parmi les candidats fournis (pas un compte fourre-tout si un "
        "compte précis convient). Respecte scrupuleusement les règles de chaque "
        "candidat : un repas/restaurant va en Réceptions, pas en Missions. "
        "Renvoie seulement le numéro de compte, ta justification et ta confiance.\n\n"
        f"Dépense : {ex.model_dump_json()}\n\n"
        f"Candidats :\n{lignes}"
    )
    choice: CodingChoice = structured(CodingChoice).invoke(prompt)

    # On récupère l'entrée du référentiel correspondant au compte choisi.
    # Le taux de TVA et la déductibilité viennent du RÉFÉRENTIEL, pas du LLM :
    # il n'a pas pu les inventer. (Fallback : 1er candidat si compte hors liste.)
    entry = next((c for c in candidates if c["compte"] == choice.compte), candidates[0])

    coding = Coding(
        compte=entry["compte"],
        libelle=entry["libelle"],
        tva_taux=float(entry["tva_usuelle"]),
        deductible=bool(entry["deductible"]),
        justification=choice.justification,
        confidence=choice.confidence,
    )
    return {"coding": coding, "retrieved": candidates}


# --- Nœud 3 : RÉDACTION (déterministe) -------------------------------------
def draft_node(state: GraphState) -> dict:
    ex, co = state.extraction, state.coding
    ttc = ex.montant_ttc or 0.0

    # Le taux imprimé sur le justificatif FAIT FOI (c'est la pièce comptable) ;
    # le taux usuel du référentiel n'est qu'un défaut quand la source ne le donne
    # pas (dictée vocale sans taux, par ex.).
    taux = ex.tva_taux if ex.tva_taux is not None else (co.tva_taux or 0.0)

    # Calcul comptable — PUR PYTHON, aucune IA sur les chiffres.
    ht = round(ttc / (1 + taux / 100), 2) if taux else round(ttc, 2)
    tva = round(ttc - ht, 2)

    ecriture = Ecriture(
        compte_charge=co.compte,
        montant_ht=ht,
        montant_tva=tva,
        montant_ttc=round(ttc, 2),
        libelle_ecriture=f"{co.libelle} — {ex.marchand or 'fournisseur'}"
        + (f" ({ex.motif})" if ex.motif else ""),
    )
    return {"ecriture": ecriture}


# --- Nœud 4 : VÉRIFICATION (agent indépendant) -----------------------------
def verify_node(state: GraphState) -> dict:
    ex, co, ec = state.extraction, state.coding, state.ecriture

    prompt = (
        "Tu es contrôleur comptable INDÉPENDANT. Vérifie cette écriture SANS "
        "rien réécrire toi-même. Contrôle :\n"
        "1. Ancrage : tout vient-il bien de la dictée d'origine (rien d'inventé) ?\n"
        "2. TVA : le taux et la déductibilité collent-ils au compte choisi ?\n"
        "3. Arithmétique : HT + TVA = TTC ?\n"
        "4. Complétude : des champs manquants empêchent-ils la validation ?\n\n"
        f"Dictée d'origine : « {state.transcript} »\n"
        f"Extraction : {ex.model_dump_json()}\n"
        f"Codage : {co.model_dump_json()}\n"
        f"Écriture : {ec.model_dump_json()}\n\n"
        "Si un champ essentiel manque (montant, date) → needs_human=true. "
        "Si le codage/TVA semble faux mais corrigeable → ok=false + "
        "correction_hint. Sinon ok=true."
    )
    result: Verification = structured(Verification).invoke(prompt)

    # Garde-fou déterministe : le taux TVA imprimé sur le justificatif doit
    # coller au taux usuel du compte choisi. S'ils divergent, on ne l'avale pas
    # en silence — on lève un avertissement (compte mal deviné ou dépense à taux
    # atypique). Le montant reste juste (calculé sur le taux du reçu), mais le
    # CODAGE mérite un œil humain.
    if (
        ex.tva_taux is not None
        and co.tva_taux is not None
        and abs(ex.tva_taux - co.tva_taux) > 0.01
    ):
        result.issues.append(
            Issue(
                champ="tva_taux",
                probleme=(
                    f"Taux TVA du justificatif ({ex.tva_taux}%) ≠ taux usuel du "
                    f"compte {co.compte} ({co.tva_taux}%) : vérifier le compte ou "
                    "la nature de la dépense."
                ),
                severite="avertissement",
            )
        )

    # Garde-fou déterministe : SEUL le montant est bloquant (sans montant, pas
    # d'écriture possible). Une date manquante n'escalade pas — on la traitera
    # à la validation. On ne délègue pas cette règle-métier au LLM.
    if ex.montant_ttc is None:
        result.needs_human = True
        result.ok = False
    return {"verification": result}
