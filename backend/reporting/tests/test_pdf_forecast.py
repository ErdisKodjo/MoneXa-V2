"""
Tests exports PDF (journal de caisse, bilan) + saisonnalité jours de marché.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from finance.models import Expense, Invoice, Payment
from finance.services.forecast import (
    _apply_market_seasonality,
    _calibrate_market_ratios,
    forecast_cashflow,
)


@pytest.fixture
def gerant(django_user_model):
    user = django_user_model.objects.create_user(
        email="pdf@monexa.tg", password="Monexa2026!", role="GERANT"
    )
    return user


@pytest.fixture
def data(db, gerant):
    now = timezone.now()
    for i in range(5):
        Payment.objects.create(
            provider_ref=f"TMXPDF{i:02d}",
            amount=Decimal("10000") + i,
            channel="TMONEY",
            payer_name=f"Client {i}",
            paid_at=now - timedelta(days=i),
            status="RECONCILIE",
            created_by=gerant,
        )
        Expense.objects.create(
            supplier=f"Fournisseur {i}",
            category="FOURNISSEURS",
            amount=Decimal("2000") + i,
            paid_at=now - timedelta(days=i),
            created_by=gerant,
        )
    Invoice.objects.create(
        reference="FACT-2026-7001",
        client_name="Client PDF",
        amount=Decimal("5000"),
        issue_date=timezone.localdate() - timedelta(days=2),
        due_date=timezone.localdate() + timedelta(days=12),
        created_by=gerant,
    )


def test_journal_pdf_bytes(db, client, gerant, data):
    client.force_login(gerant)
    resp = client.get(reverse("export_pdf_journal"))
    assert resp.status_code == 200
    assert resp["Content-Type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF")


def test_bilan_pdf_30_and_90_days(db, client, gerant, data):
    client.force_login(gerant)
    for days in ("30", "90"):
        resp = client.get(reverse("export_pdf_bilan"), {"days": days})
        assert resp.status_code == 200
        assert resp.content.startswith(b"%PDF")


def test_bilan_pdf_invalid_days_defaults(db, client, gerant, data):
    client.force_login(gerant)
    resp = client.get(reverse("export_pdf_bilan"), {"days": "9999999999"})
    assert resp.status_code == 200


def test_market_ratio_calibration():
    # Samedi (weekday 5) x4 — détecté puis borné à 2.0
    historical = [
        {"date": "2026-09-21", "net": 100.0},  # lundi
        {"date": "2026-09-22", "net": 100.0},
        {"date": "2026-09-23", "net": 100.0},
        {"date": "2026-09-24", "net": 100.0},
        {"date": "2026-09-25", "net": 100.0},
        {"date": "2026-09-26", "net": 400.0},  # samedi marché
        {"date": "2026-09-27", "net": 100.0},  # dimanche
    ]
    ratios = _calibrate_market_ratios(historical)
    assert ratios.get(5) == 2.0  # borné sup
    assert ratios.get(0) < 1.0


def test_market_seasonality_boosts_configured_day(monkeypatch):
    monkeypatch.setattr("finance.services.forecast.market_weekdays", lambda: [5])
    forecast = [100.0] * 7
    adjusted = _apply_market_seasonality(forecast, {5: 2.0})
    boosted = [v for v, orig in zip(adjusted, forecast) if v > orig]
    assert len(boosted) >= 1  # au moins un samedi boosté


def test_forecast_contains_market_metadata(db, data):
    result = forecast_cashflow(days=7)
    assert "market_days" in result
    assert "market_ratios" in result
    assert len(result["forecast"]) == 7
