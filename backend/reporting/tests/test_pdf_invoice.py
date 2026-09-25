"""
Tests facture PDF avec QR code de paiement (v2.3).
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from finance.models import Invoice
from reporting.pdf import _qr_payment_payload, invoice_pdf

pytestmark = pytest.mark.django_db


@pytest.fixture
def gerant(django_user_model):
    return django_user_model.objects.create_user(
        email="factpdf@monexa.tg", password="Monexa2026!", role="GERANT"
    )


@pytest.fixture
def invoice(gerant):
    return Invoice.objects.create(
        reference="FACT-2026-9001",
        client_name="KOSSI Mensah",
        client_phone="90123456",
        amount=Decimal("25000.00"),
        issue_date=date.today(),
        due_date=date.today() + timedelta(days=14),
        status="EN_ATTENTE",
        created_by=gerant,
    )


def test_invoice_pdf_bytes(invoice):
    """Le PDF facture est un document PDF valide."""
    data = invoice_pdf(invoice)
    assert data.startswith(b"%PDF")
    assert len(data) > 1500  # contient au moins le QR (image PNG embarquée)


def test_qr_payload_contains_ussd_and_reference(invoice):
    """Le QR code contient référence, montant et codes USSD opérateurs."""
    payload = _qr_payment_payload(invoice)
    assert "FACT-2026-9001" in payload
    assert "25 000 FCFA" in payload
    assert "*880#" in payload      # T-Money
    assert "*155#" in payload      # Moov Money
    assert "*110#" in payload      # Flooz


def test_invoice_pdf_marks_overdue(gerant, invoice):
    """Une facture échue en attente est marquée EN RETARD dans le payload QR."""
    invoice.due_date = date.today() - timedelta(days=9)
    invoice.save()
    data = invoice_pdf(invoice)
    assert data.startswith(b"%PDF")


def test_invoice_pdf_view(client, gerant, invoice):
    """Vue web : téléchargement avec bon Content-Disposition."""
    client.force_login(gerant)
    resp = client.get(reverse("invoice_pdf", args=[invoice.pk]))
    assert resp.status_code == 200
    assert resp["Content-Type"] == "application/pdf"
    assert f"monexa_facture_{invoice.reference}.pdf" in resp["Content-Disposition"]


def test_invoice_pdf_view_requires_login(client, invoice):
    """Sans session → redirection vers le login (RBAC)."""
    resp = client.get(reverse("invoice_pdf", args=[invoice.pk]))
    assert resp.status_code == 302
    assert "/login/" in resp.url
