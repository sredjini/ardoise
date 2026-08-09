from app.agents import draft_node, verify_node
from app.graph import _reject_node, _route_after_extract, _route_after_verify
from app.schemas import Coding, Extraction, GraphState, Verification


def _coding(tva_taux: float = 20.0) -> Coding:
    return Coding(
        compte="6251",
        libelle="Voyages et déplacements",
        tva_taux=tva_taux,
        deductible=True,
        justification="Taxi professionnel",
        confidence=0.92,
    )


def test_draft_node_computes_vat_deterministically() -> None:
    state = GraphState(
        transcript="taxi gare hotel 34 euros",
        extraction=Extraction(
            est_une_depense=True,
            marchand="Taxi G7",
            motif="déplacement client Lyon",
            montant_ttc=34.0,
        ),
        coding=_coding(tva_taux=20.0),
    )

    result = draft_node(state)

    assert result["ecriture"].montant_ttc == 34.0
    assert result["ecriture"].montant_ht == 28.33
    assert result["ecriture"].montant_tva == 5.67
    assert result["ecriture"].compte_charge == "6251"
    assert "Taxi G7" in result["ecriture"].libelle_ecriture


def test_extract_routing_rejects_non_expenses() -> None:
    state = GraphState(
        transcript="bonjour ceci est hors sujet",
        extraction=Extraction(est_une_depense=False),
    )

    assert _route_after_extract(state) == "reject"

    result = _reject_node(state)
    verification = result["verification"]
    assert verification.ok is False
    assert verification.needs_human is False
    assert verification.issues[0].severite == "bloquant"


def test_verify_node_forces_human_review_when_amount_is_missing(monkeypatch) -> None:
    class FakeRunnable:
        def invoke(self, _prompt: str) -> Verification:
            return Verification(ok=True, needs_human=False)

    monkeypatch.setattr("app.agents.structured", lambda _schema: FakeRunnable())

    state = GraphState(
        transcript="déjeuner avec un client",
        extraction=Extraction(
            est_une_depense=True,
            marchand="Restaurant",
            motif="déjeuner client",
            montant_ttc=None,
        ),
        coding=_coding(tva_taux=10.0),
        ecriture=draft_node(
            GraphState(
                transcript="déjeuner avec un client",
                extraction=Extraction(
                    est_une_depense=True,
                    marchand="Restaurant",
                    motif="déjeuner client",
                    montant_ttc=None,
                ),
                coding=_coding(tva_taux=10.0),
            )
        )["ecriture"],
    )

    result = verify_node(state)

    assert result["verification"].ok is False
    assert result["verification"].needs_human is True


def test_verify_routing_retries_only_for_correctable_failures() -> None:
    retry_state = GraphState(
        transcript="taxi 34 euros",
        verification=Verification(ok=False, needs_human=False, correction_hint="recoder"),
        retries=0,
    )
    human_state = GraphState(
        transcript="restaurant client",
        verification=Verification(ok=False, needs_human=True),
        retries=0,
    )
    validated_state = GraphState(
        transcript="taxi 34 euros",
        verification=Verification(ok=True, needs_human=False),
        retries=0,
    )

    assert _route_after_verify(retry_state) == "retry"
    assert _route_after_verify(human_state) == "end"
    assert _route_after_verify(validated_state) == "end"
