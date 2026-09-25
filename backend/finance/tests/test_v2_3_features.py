"""
Tests scoring fiabilité clients + relances impayés + rapport hebdo (v2.3).
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from accounts.models import Notification, Role
from finance.models import Invoice, Payment
from finance.services.client_scoring import (
    client_reliability_scores,
    risky_clients,
)
from finance.services.reminders import (
    build_reminder_message,
    create_reminders,
    overdue_invoices,
)
from finance.services.weekly_report import generate_weekly_report

pytestmark = pytest.mark.django_db


@pytest.fixture
def gerant(django_user_model):
    return django_user_model.objects.create_user(
        email="score@monexa.tg", password="Monexa2026!", role="GERANT"
    )


@pytest.fixture
def comptable(django_user_model):
    return django_user_model.objects.create_user(
        email="compta-score@monexa.tg", password="Monexa2026!", role="COMPTABLE"
    )


# ────────────────────────────────────────────────────────────────────────
# Scoring fiabilité clients
# ────────────────────────────────────────────────────────────────────────
def _mk_invoice(gerant, ref, client, amount, issue, due, status="EN_ATTENTE"):
    return Invoice.objects.create(
        reference=ref, client_name=client, amount=Decimal(amount),
        issue_date=issue, due_date=due, status=status, created_by=gerant,
    )


def _mk_payment(gerant, ref, amount, paid_at, client=None, payer="X", status="RECONCILIE", channel="TMONEY"):
    return Payment.objects.create(
        provider_ref=ref, amount=Decimal(amount), channel=channel,
        payer_name=payer, paid_at=paid_at, status=status,
        invoice=client, created_by=gerant,
    )


def test_score_client_fiable(gerant):
    """Client qui paie à l'heure → score élevé, label Fiable."""
    today = timezone.localdate()
    inv = _mk_invoice(gerant, "FACT-2026-8001", "Bon Client", "10000", today - timedelta(days=20), today - timedelta(days=10))
    _mk_payment(gerant, "TMXSCORE01", "10000", timezone.now() - timedelta(days=12), client=inv)
    inv.status = "RECONCILIE"
    inv.save()

    scores = {c["name"]: c for c in client_reliability_scores()}
    assert "Bon Client" in scores
    c = scores["Bon Client"]
    assert c["score"] >= 80
    assert c["label"] == "Fiable"
    assert c["tone"] == "success"


def test_score_client_en_retard(gerant):
    """Facture échue non payée → pénalité, score < 80."""
    today = timezone.localdate()
    _mk_invoice(gerant, "FACT-2026-8002", "Client Retard", "50000", today - timedelta(days=30), today - timedelta(days=15))

    scores = {c["name"]: c for c in client_reliability_scores()}
    c = scores["Client Retard"]
    assert c["late_open"] == 1
    assert c["outstanding"] == 50000.0
    assert c["score"] < 80
    assert c["label"] in ("Vigilance", "Risque")


def test_score_client_anomalies_penalisees(gerant):
    """Paiements en anomalie → pénalité supplémentaire."""
    today = timezone.localdate()
    inv = _mk_invoice(gerant, "FACT-2026-8003", "Client Risqué", "20000", today - timedelta(days=10), today + timedelta(days=4))
    _mk_payment(gerant, "TMXSCORE02", "20000", timezone.now(), client=inv, status="ANOMALIE")

    scores = {c["name"]: c for c in client_reliability_scores()}
    c = scores["Client Risqué"]
    assert c["anomalies"] == 1
    assert c["score"] <= 85  # anomalie = au moins la pénalité anomalie


def test_scores_tries_du_plus_risque(gerant):
    """Le moins fiable apparaît en premier."""
    today = timezone.localdate()
    _mk_invoice(gerant, "FACT-2026-8004", "AAA Mauvais", "30000", today - timedelta(days=40), today - timedelta(days=25))
    inv2 = _mk_invoice(gerant, "FACT-2026-8005", "BBB Bon", "10000", today - timedelta(days=20), today - timedelta(days=10))
    _mk_payment(gerant, "TMXSCORE03", "10000", timezone.now() - timedelta(days=12), client=inv2)
    inv2.status = "RECONCILIE"
    inv2.save()

    scores = client_reliability_scores()
    assert scores[0]["name"] == "AAA Mauvais"


def test_risky_clients_limite(gerant):
    today = timezone.localdate()
    _mk_invoice(gerant, "FACT-2026-8006", "Risque Alpha", "1000", today - timedelta(days=30), today - timedelta(days=20))
    assert risky_clients(limit=1)[0]["name"] == "Risque Alpha"


def test_scores_base_vide(gerant):
    """Base vide → liste vide, jamais d'erreur."""
    assert client_reliability_scores() == []


# ────────────────────────────────────────────────────────────────────────
# Relances impayés
# ────────────────────────────────────────────────────────────────────────
def test_overdue_invoices_seuil_7j(gerant):
    """Seules les factures échues de PLUS de 7 jours sont relancées."""
    today = timezone.localdate()
    _mk_invoice(gerant, "FACT-2026-8010", "Client OK", "1000", today - timedelta(days=5), today - timedelta(days=2))    # trop récente
    _mk_invoice(gerant, "FACT-2026-8011", "Client Limite", "1000", today - timedelta(days=30), today - timedelta(days=7))  # exactement 7j → non
    _mk_invoice(gerant, "FACT-2026-8012", "Client Due", "1000", today - timedelta(days=30), today - timedelta(days=10))  # 10j → oui
    _mk_invoice(gerant, "FACT-2026-8013", "Client Payé", "1000", today - timedelta(days=30), today - timedelta(days=20), status="RECONCILIE")  # payée

    refs = [i.reference for i in overdue_invoices(days=7)]
    assert refs == ["FACT-2026-8012"]


def test_build_reminder_message_fallback_template(gerant):
    """Sans clé API (pytest) → template déterministe, source=TEMPLATE."""
    today = timezone.localdate()
    inv = _mk_invoice(gerant, "FACT-2026-8014", "KOSSI Mensah", "25000", today - timedelta(days=30), today - timedelta(days=10))
    msg, source = build_reminder_message(inv, use_llm=True)
    assert source == "TEMPLATE"
    assert "FACT-2026-8014" in msg
    assert "25 000 FCFA" in msg
    assert "10 jour" in msg
    assert "*880#" in msg


def test_create_reminders_notifie_gerant_et_comptable(gerant, comptable):
    today = timezone.localdate()
    _mk_invoice(gerant, "FACT-2026-8015", "Client Relance", "12000", today - timedelta(days=40), today - timedelta(days=12))

    created = create_reminders(days=7)
    assert len(created) == 1
    assert created[0]["source"] == "TEMPLATE"

    notifs = Notification.objects.filter(kind="RAPPEL_FACTURE")
    assert notifs.count() == 2  # gérant + comptable
    assert {n.user.role for n in notifs} == {Role.GERANT, Role.COMPTABLE}
    assert "FACT-2026-8015" in notifs.first().body


def test_create_reminders_anti_spam_meme_jour(gerant, comptable):
    """Deux exécutions le même jour → une seule vague de notifications."""
    today = timezone.localdate()
    _mk_invoice(gerant, "FACT-2026-8016", "Client Spam", "9000", today - timedelta(days=40), today - timedelta(days=12))

    create_reminders(days=7)
    create_reminders(days=7)  # 2e passe le même jour
    assert Notification.objects.filter(kind="RAPPEL_FACTURE").count() == 2


def test_create_reminders_dry_run_n_ecrit_pas(gerant, comptable):
    today = timezone.localdate()
    _mk_invoice(gerant, "FACT-2026-8017", "Client Dry", "7000", today - timedelta(days=40), today - timedelta(days=12))
    created = create_reminders(days=7, dry_run=True)
    assert len(created) == 1
    assert Notification.objects.filter(kind="RAPPEL_FACTURE").count() == 0


def test_create_reminders_rien_a_relancer(gerant):
    assert create_reminders(days=7) == []


# ────────────────────────────────────────────────────────────────────────
# Rapport hebdomadaire
# ────────────────────────────────────────────────────────────────────────
def test_weekly_report_template_deterministe(gerant):
    """Sans LLM → synthèse déterministe contenant les chiffres clés."""
    text, source = generate_weekly_report(use_llm=True)
    assert source == "TEMPLATE"  # garde pytest : pas d'appel réseau
    assert "FCFA" in text
    assert "Rapport hebdomadaire" in text


def test_weekly_report_avec_chiffres(gerant):
    today = timezone.localdate()
    _mk_payment(gerant, "TMXREPORT01", "45000", timezone.now() - timedelta(days=2))
    text, _ = generate_weekly_report(use_llm=False)
    assert "45 000 FCFA" in text  # encaissé 7j reflété dans le rapport
