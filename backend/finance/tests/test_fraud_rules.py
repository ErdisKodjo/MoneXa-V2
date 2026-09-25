"""
Tests des règles anti-fraude SMS (numéros usurpés, refs falsifiées, rafales).
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from finance.models import Payment
from finance.services.anomalies import _detect_fraud_rules, scan_recent_fraud


def _make_payment(**kwargs):
    defaults = dict(
        provider_ref="TMX0001",
        amount=Decimal("10000"),
        channel="TMONEY",
        payer_name="Client Test",
        payer_phone="+228 90 11 22 33",
        paid_at=timezone.now(),
        raw_text="[SMS RULES] Paiement de 10 000 FCFA",
        ai_confidence=0.95,
    )
    defaults.update(kwargs)
    return Payment(**defaults)


def test_wrong_operator_number_flagged(db):
    p = _make_payment(payer_phone="+228 94 55 66 77", channel="TMONEY")
    types = [a["type"] for a in _detect_fraud_rules(p)]
    assert "Numéro incompatible avec le canal" in types


def test_valid_operator_number_not_flagged(db):
    p = _make_payment(payer_phone="+228 91 11 22 33", channel="TMONEY")
    types = [a["type"] for a in _detect_fraud_rules(p)]
    assert "Numéro incompatible avec le canal" not in types


def test_forged_reference_flagged(db):
    p = _make_payment(provider_ref="FL9999", channel="TMONEY")
    types = [a["type"] for a in _detect_fraud_rules(p)]
    assert "Référence suspecte" in types


def test_burst_detection(db, django_user_model):
    user = django_user_model.objects.create_user(
        email="burst@test.tg", password="Monexa2026!", role="CAISSIER"
    )
    now = timezone.now()
    base = dict(
        amount=Decimal("1000"), channel="TMONEY",
        payer_name="Rafale", payer_phone="+228 90 77 88 99",
        ai_confidence=0.95, created_by=user,
    )
    Payment.objects.create(provider_ref="TMXB1", paid_at=now - timedelta(minutes=2), **base)
    Payment.objects.create(provider_ref="TMXB2", paid_at=now - timedelta(minutes=1), **base)
    p = Payment(provider_ref="TMXB3", paid_at=now, **base)
    p.save()
    types = [a["type"] for a in _detect_fraud_rules(p)]
    assert "Rafale de paiements" in types
    flagged = scan_recent_fraud(limit=10)
    assert any(f["type"] == "Rafale de paiements" for f in flagged)


def test_phishing_sms_flagged(db):
    p = _make_payment(
        raw_text="[SMS] Votre compte est bloqué, envoyez votre PIN pour le débloquer"
    )
    types = [a["type"] for a in _detect_fraud_rules(p)]
    assert "SMS suspect (hameçonnage)" in types


def test_bank_channel_skips_operator_rules(db):
    p = _make_payment(channel="BANQUE", payer_phone="+228 22 55 00 11")
    types = [a["type"] for a in _detect_fraud_rules(p)]
    assert "Numéro incompatible avec le canal" not in types
