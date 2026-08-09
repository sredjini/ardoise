"""
graph.py — Le graphe LangGraph. C'EST l'architecture, rendue exécutable.

Concepts LangGraph (les seuls à retenir) :
  - StateGraph(GraphState) : un graphe dont l'état partagé est notre Pydantic.
  - add_node(name, fn)     : un nœud = une fonction (état) -> maj d'état.
  - add_edge(a, b)         : arête FIXE (toujours a puis b).
  - add_conditional_edges  : arête DYNAMIQUE : une fonction décide où aller.
                             → c'est ça qui transforme la chaîne en système.

Flux :
  extract → code → draft → verify → [décision]
                                       ├─ ok            → END
                                       ├─ needs_human   → END
                                       ├─ corrigeable   → bump → extract (boucle)
                                       └─ retries épuisés→ END
"""

from langgraph.graph import StateGraph, END

from .schemas import GraphState, Verification, Issue
from .agents import extract_node, code_node, draft_node, verify_node
from .config import settings


def _bump_retries(state: GraphState) -> dict:
    """Nœud minuscule : incrémente le compteur avant de reboucler."""
    return {"retries": state.retries + 1}


def _reject_node(state: GraphState) -> dict:
    """Entrée non exploitable : on rejette proprement, sans rien fabriquer."""
    return {
        "verification": Verification(
            ok=False,
            needs_human=False,
            issues=[
                Issue(
                    champ="entrée",
                    probleme="Le texte ne décrit pas une dépense professionnelle exploitable.",
                    severite="bloquant",
                )
            ],
        )
    }


def _route_after_extract(state: GraphState) -> str:
    """Aiguillage : dépense valable → codage ; sinon → rejet."""
    if state.extraction and not state.extraction.est_une_depense:
        return "reject"
    return "code"


def _route_after_verify(state: GraphState) -> str:
    """La fonction de décision : renvoie le nom de la prochaine étape."""
    v = state.verification
    if v is None:
        return "end"
    if v.ok:
        return "end"                       # écriture validée
    if v.needs_human:
        return "end"                       # ambiguïté irréductible → humain
    if state.retries < settings.MAX_RETRIES:
        return "retry"                     # corrigeable → on reboucle
    return "end"                           # garde-fou : on n'insiste pas indéfiniment


def build_graph():
    g = StateGraph(GraphState)

    g.add_node("extract", extract_node)
    g.add_node("code", code_node)
    g.add_node("draft", draft_node)
    g.add_node("verify", verify_node)
    g.add_node("bump", _bump_retries)
    g.add_node("reject", _reject_node)

    g.set_entry_point("extract")
    # Aiguillage après extraction : dépense valable → codage ; sinon → rejet.
    g.add_conditional_edges(
        "extract", _route_after_extract, {"code": "code", "reject": "reject"}
    )
    g.add_edge("reject", END)
    g.add_edge("code", "draft")            # arêtes fixes du happy-path
    g.add_edge("draft", "verify")

    # Arête conditionnelle : la vérif décide de la suite.
    g.add_conditional_edges(
        "verify",
        _route_after_verify,
        {"end": END, "retry": "bump"},
    )
    g.add_edge("bump", "extract")          # la boucle : bump → on ré-extrait

    return g.compile()


# Compilé une fois au chargement du module.
compiled_graph = build_graph()
