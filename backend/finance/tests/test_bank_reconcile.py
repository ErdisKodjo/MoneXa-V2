"""
Tests du rapprochement bancaire multi-comptes (v2.3).
"""
from datetime import timedelta
from io import BytesIO

import pytest
from django.utils import timezone

from finance.models import Channel, Invoice, Payment, PaymentStatus
from finance.services.bank_reconcile import (
    bank_provider_ref,
    parse_bank_csv,
    reconcile_bank_statement,
)

CSV_HEADER = "date;libelle;reference;credit;debit\n"


@pytest.fixture
def invoice(db):
    return Invoice.objects.create(
        reference="FACT-2026-0001",
        client_name="BTP PLUS SARL",
        client_phone="+228 90 11 22 33",
        amount=150000,
        issue_date=timezone.now().date(),
        due_date=timezone.now().date() + timedelta(days=15),
        created_by_id=1,
    )


@pytest.fixture
def gerant(db):
    from accounts.models import User, Role
    return User.objects.create_user(
        email="banker@monexa.tg", password="Monexa2026!", role=Role.GERANT,
    )


class TestParseBankCsv:
    def test_parse_header_and_french_amounts(self):
        csv_bytes = (
            CSV_HEADER
            + "02/09/2026;VIREMENT RECU FACT-2026-0001;VIR001;150 000;0\n"
            + "05/09/2026;CHEQUE CLIENT;CHQ002;1 234 567,89;0\n"
        ).encode("utf-8")
        lines, errors, debits = parse_bank_csv(csv_bytes)
        assert errors == []
        assert len(lines) == 2
        assert str(lines[0].montant) == "150000"
        assert str(lines[1].montant) == "1234567.89"
        assert lines[0].reference == "VIR001"
        assert debits == 0

    def test_parse_debits_ignored(self):
        csv_bytes = (
            CSV_HEADER
            + "02/09/2026;VIREMENT RECU;VIR001;150000;0\n"
            + "03/09/2026;PAIEMENT LOYER;PRLV09;0;250000\n"
        ).encode("utf-8")
        lines, errors, debits = parse_bank_csv(csv_bytes)
        assert len(lines) == 1
        assert debits == 1

    def test_parse_without_header_positional(self):
        csv_bytes = (
            "02/09/2026;VIREMENT FACT-2026-0001;VIR777;50000;0\n"
        ).encode("utf-8")
        lines, errors, debits = parse_bank_csv(csv_bytes)
        assert len(lines) == 1
        assert lines[0].reference == "VIR777"

    def test_bad_date_reported(self):
        csv_bytes = (
            CSV_HEADER
            + "02/13/2026;DATE INVALIDE;VIR404;1000;0\n"
        ).encode("utf-8")
        lines, errors, debits = parse_bank_csv(csv_bytes)
        assert lines == []
        assert any("Ligne 2" in e for e in errors)


class TestReconcile:
    def _import(self, gerant, csv_text):
        lines, errors, debits = parse_bank_csv(csv_text.encode("utf-8"))
        return reconcile_bank_statement(lines, created_by=gerant,
                                        debits_ignored=debits, errors=errors)

    @pytest.mark.django_db
    def test_match_by_reference(self, gerant, invoice):
        csv_text = CSV_HEADER + "05/09/2026;VIREMENT FACT-2026-0001;VIR100;150000;0\n"
        report = self._import(gerant, csv_text)
        assert report.imported == 1
        assert report.matched_ref == 1
        payment = Payment.objects.get(provider_ref="BQ-VIR100")
        assert payment.channel == Channel.BANQUE
        assert payment.status == PaymentStatus.RECONCILIE
        assert payment.invoice_id == invoice.id

    @pytest.mark.django_db
    def test_idempotent_reimport(self, gerant, invoice):
        csv_text = CSV_HEADER + "05/09/2026;VIREMENT FACT-2026-0001;VIR100;150000;0\n"
        self._import(gerant, csv_text)
        report = self._import(gerant, csv_text)
        assert report.imported == 0
        assert report.skipped == 1
        assert Payment.objects.count() == 1

    @pytest.mark.django_db
    def test_unmatched_line(self, gerant, invoice):
        csv_text = CSV_HEADER + "07/09/2026;VIREMENT INCONNU;VIR999;999999;0\n"
        report = self._import(gerant, csv_text)
        assert report.imported == 1
        assert report.non_rattaches == 1
        payment = Payment.objects.get(provider_ref="BQ-VIR999")
        assert payment.status == PaymentStatus.NON_RATTACHE

    @pytest.mark.django_db
    def test_hashed_ref_without_bank_reference(self, gerant, invoice):
        csv_text = CSV_HEADER + "08/09/2026;DEPOT ESPECES SANS REF;;25000;0\n"
        report = self._import(gerant, csv_text)
        assert report.imported == 1
        payment = Payment.objects.first()
        assert payment.provider_ref.startswith("BQ-")
        assert len(payment.provider_ref) == 15  # BQ- + 12 hex

    def test_stable_hash(self):
        from datetime import datetime
        line = type("L", (), {
            "date": datetime(2026, 9, 8, 12, 0),
            "libelle": "DEPOT", "montant": __import__("decimal").Decimal("25000"),
            "reference": "", "row": 2, "extra_debit": __import__("decimal").Decimal("0"),
        })()
        assert bank_provider_ref(line) == bank_provider_ref(line)
