"""
Tests du parser SMS déterministe (T-Money / Moov / Flooz) et de l'OCR.
"""
import pytest
from datetime import timezone

from finance.services.ai_pipeline import (
    extract_payment_from_text,
    parse_sms_payment,
    pipeline_status,
)


SMS_TMONEY = (
    "Vous avez reçu 25 000 FCFA de KOSSI Mensah (90123456) le 24/09/2026 à 14:23. "
    "Ref: TMX260924.1432.A12345. Solde: 150 000 FCFA."
)
SMS_MOOV = (
    "Transfert recu de AFI Adjovi (94123456). Montant: 10 000 FCFA. "
    "ID Transaction: MP260924.1430.B98765. Nouveau solde: 60 000 FCFA."
)
SMS_FLOOZ = (
    "Vous avez envoyé 15 000 FCFA à MONEXA BOUTIQUE (96888888) le 25-09-2026 a 09:15. "
    "Ref: FL123456789012."
)


def test_parser_tmoney_full():
    r = parse_sms_payment(SMS_TMONEY)
    assert r is not None
    assert r.montant == 25000
    assert r.operator == "TMONEY"
    assert r.reference == "TMX260924.1432.A12345"
    assert r.emetteur == "KOSSI Mensah"
    assert r.telephone_emetteur == "+228 90 12 34 56"
    assert r.date_paiement.year == 2026 and r.date_paiement.hour == 14


def test_parser_moov_full():
    r = parse_sms_payment(SMS_MOOV)
    assert r is not None
    assert r.montant == 10000
    assert r.operator == "MOOV"
    assert r.reference == "MP260924.1430.B98765"
    assert r.emetteur == "AFI Adjovi"


def test_parser_flooz_client_side_sms():
    r = parse_sms_payment(SMS_FLOOZ)
    assert r is not None
    assert r.montant == 15000
    assert r.operator == "FLOOZ"
    assert r.emetteur == "MONEXA BOUTIQUE"
    assert r.telephone_emetteur == "+228 96 88 88 88"


def test_parser_rejects_garbage():
    assert parse_sms_payment("Bonjour, comment allez-vous ?") is None
    assert parse_sms_payment("") is None
    assert parse_sms_payment("Montant: 5000 FCFA sans reference") is None


def test_extract_from_text_uses_sms_rules_first():
    result = extract_payment_from_text(SMS_TMONEY)
    assert result["ai_confidence"] == 0.95  # tag SMS RULES
    assert result["operator"] == "TMONEY"
    assert result["raw_text"].startswith("[SMS RULES]")


def test_pipeline_status_reports_mode():
    status = pipeline_status()
    assert status["level"] in ("premium", "local", "demo")
    assert isinstance(status["ocr_available"], bool)
