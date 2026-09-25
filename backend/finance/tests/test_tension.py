"""
Tests alerte de tension de trésorerie (v2.3 — « ANTICIPER »).
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from finance.models import ForecastCache, Payment
from finance.services.tension import tension_alert

pytestmark = pytest.mark.django_db


@pytest.fixture
def gerant(django_user_model):
    return django_user_model.objects.create_user(
        email="tension@monexa.tg", password="Monexa2026!", role="GERANT"
    )


def _solde(amount: str):
    Payment.objects.create(
        provider_ref="TMXTENSION01",
        amount=Decimal(amount),
        channel="TMONEY",
        payer_name="Seed",
        paid_at=timezone.now(),
        status="RECONCILIE",
        created_by=__import__("accounts.models", fromlist=["User"]).User.objects.first(),
    )


def _cache(days, forecast, low=None):
    ForecastCache.objects.create(
        days=days,
        forecast_data=forecast,
        confidence_low=low if low is not None else forecast,
        confidence_high=forecast,
    )


def test_tension_detectee_avec_cause(gerant):
    """Sorties prévues massives → alerte avec jours, balance et cause."""
    _solde("1000000")
    # Décaissement massif J+5 (dépasse le solde) puis flux neutres
    forecast = [0, 0, 0, 0, -1100000] + [100] * 25
    _cache(30, forecast)
    alert = tension_alert()
    assert alert is not None
    assert alert["days_away"] == 5
    assert alert["balance_pessimist"] < 0
    assert alert["severity"] == "ÉLEVÉE"
    assert "sortie nette" in alert["cause"]


def test_tension_seuil_moderate(gerant):
    """Balance qui reste positive mais sous le plancher 15 % → MODÉRÉE."""
    _solde("1000000")
    # Baisse lente : balance ~ -80k en fin de course (au-dessus de 0, sous plancher 150k)
    forecast = [-40000] * 30
    _cache(30, forecast)
    alert = tension_alert()
    assert alert is not None
    assert alert["severity"] == "MODÉRÉE"
    assert alert["balance_pessimist"] >= 0


def test_tresorerie_saine(gerant):
    """Flux positifs → aucune alerte."""
    _solde("1000000")
    _cache(30, [5000] * 30)
    assert tension_alert() is None


def test_base_vide_pas_derreur(gerant):
    """Base vide → None (pas de projection significative), jamais de crash."""
    assert tension_alert() is None


def test_fallback_sans_cache(gerant):
    """Sans ForecastCache → calcul Holt-Winters à la volée, sans crash."""
    now = timezone.now()
    for i in range(20):
        Payment.objects.create(
            provider_ref=f"TMXTF{i:02d}",
            amount=Decimal("50000"),
            channel="TMONEY",
            payer_name=f"C{i}",
            paid_at=now - timedelta(days=i),
            status="RECONCILIE",
            created_by=gerant,
        )
    result = tension_alert()
    # Historique stable et positif → saine OU alerte, mais jamais d'exception
    assert result is None or "days_away" in result
