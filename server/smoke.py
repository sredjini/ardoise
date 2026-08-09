"""Smoke test : fait tourner le graphe sur 2 dictées et affiche l'état final.
Usage : uv run python smoke.py
"""
import json
from app.graph import compiled_graph
from app.schemas import GraphState

CAS = [
    "taxi de la gare à l'hôtel, 34 euros, déplacement client Lyon",
    "j'ai déjeuné avec un client au restaurant",  # montant manquant → needs_human
]


def show(transcript: str):
    print("\n" + "=" * 70)
    print("DICTÉE :", transcript)
    final = compiled_graph.invoke(GraphState(transcript=transcript))
    for key in ("extraction", "coding", "ecriture", "verification"):
        val = final.get(key)
        dumped = val.model_dump() if val else None
        print(f"\n[{key}]")
        print(json.dumps(dumped, ensure_ascii=False, indent=2))
    print(f"\nretries = {final.get('retries')}")


if __name__ == "__main__":
    for c in CAS:
        show(c)
