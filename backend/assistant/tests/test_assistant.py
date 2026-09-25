"""
Tests du chatbot TresorIA.
"""
import pytest


@pytest.mark.django_db
def test_assistant_returns_answer_for_solde_tmoney(gerant_client):
    """TresorIA répond à une question sur le solde T-Money."""
    resp = gerant_client.post("/api/assistant/ask/", {"question": "Combien ai-je en T-Money ?"}, format="json")
    assert resp.status_code == 200
    assert "T-Money" in resp.data["answer"] or "tmoney" in resp.data["answer"].lower()


@pytest.mark.django_db
def test_assistant_returns_answer_for_anomalies(gerant_client):
    """TresorIA répond à une question sur les anomalies."""
    resp = gerant_client.post("/api/assistant/ask/", {"question": "Combien d'anomalies ?"}, format="json")
    assert resp.status_code == 200
    assert "anomalie" in resp.data["answer"].lower()


@pytest.mark.django_db
def test_assistant_fallback_for_unknown_question(gerant_client):
    """TresorIA retourne une réponse fallback pour les questions inconnues."""
    resp = gerant_client.post("/api/assistant/ask/", {"question": "qqqqq xxx zzz"}, format="json")
    assert resp.status_code == 200
    assert "n'ai pas compris" in resp.data["answer"].lower() or "voici ce que" in resp.data["answer"].lower()


@pytest.mark.django_db
def test_assistant_requires_authentication(api_client):
    """L'endpoint /api/assistant/ask/ exige une authentification."""
    resp = api_client.post("/api/assistant/ask/", {"question": "test"}, format="json")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_assistant_validates_question_length(gerant_client):
    """L'endpoint valide la longueur de la question."""
    resp = gerant_client.post("/api/assistant/ask/", {"question": "ab"}, format="json")
    assert resp.status_code == 400


# ──────────────────────────────────────────────────────────────────────────
# Niveau 1 — LLM réel (TresorIA v2.2) : KPIs injectés, jamais de SQL
# ──────────────────────────────────────────────────────────────────────────

def test_serialize_kpis_contains_all_fields():
    """La sérialisation des KPIs contient les chiffres clés formatés FCFA."""
    from assistant.services import _serialize_kpis

    kpis = {
        "solde_total": 12450000.0,
        "solde_par_canal": {"TMONEY": 6200000.0, "MOOV": 3100000.0, "FLOOZ": 0.0},
        "encaisse_7j": 850000.0,
        "encaisse_30j": 3200000.0,
        "decaisse_7j": 150000.0,
        "decaisse_30j": 700000.0,
        "flux_net_30j": 2500000.0,
        "factures_en_attente": 8,
        "factures_en_retard": 3,
        "paiements_a_valider": 5,
        "nb_anomalies": 2,
        "prevision_j7": 900000.0,
        "prevision_j30": 2800000.0,
        "top_5_clients": [{"name": "Kossi Mensah", "total": 1200000.0, "count": 12}],
    }
    text = _serialize_kpis(kpis)
    assert "12 450 000 FCFA" in text
    assert "TMONEY=6 200 000 FCFA" in text
    assert "Factures en retard : 3" in text
    assert "Kossi Mensah" in text
    # Jamais de SQL ni de mention technique de DB dans le contexte
    assert "SELECT" not in text.upper()


def test_build_llm_prompt_injects_kpis_and_question():
    """Le prompt LLM contient les règles anti-hallucination + KPIs + question."""
    from assistant.services import _build_llm_prompt

    prompt = _build_llm_prompt("Quel est mon solde total ?", {"solde_total": 1000.0})
    assert "N'invente JAMAIS" in prompt
    assert "Jamais de SQL" in prompt
    assert "1 000 FCFA" in prompt
    assert "Quel est mon solde total ?" in prompt


@pytest.mark.django_db
def test_llm_fallback_rules_without_api_key(gerant_client, monkeypatch):
    """Sans clé API (ou sous pytest), TresorIA bascule sur le moteur de règles."""
    from assistant import services as svc

    monkeypatch.setattr(svc, "_setting", lambda name, default="": "" if "KEY" in name else default)
    answer = svc.answer_question(None, "Combien ai-je en T-Money ?")
    assert "T-Money" in answer or "tmoney" in answer.lower()


@pytest.mark.django_db
def test_llm_answer_used_when_available(monkeypatch):
    """Si le LLM répond, sa reformulation est renvoyée en priorité."""
    from assistant import services as svc

    monkeypatch.setattr(svc, "_call_llm_cfo", lambda q, k: "Réponse LLM reformulée.")
    answer = svc.answer_question(None, "Quelle est ma trésorerie ?")
    assert answer == "Réponse LLM reformulée."
