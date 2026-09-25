"""
Tests des passerelles de collecte Mobile Money (sandbox + webhook HMAC).
"""
import hashlib
import hmac
from decimal import Decimal

import pytest
from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from finance.models import (
    GatewayTransaction,
    GatewayTransactionStatus,
    Invoice,
    InvoiceStatus,
    Payment,
)
from finance.services.gateways import (
    confirm_gateway_transaction,
    is_live,
    request_collection,
    verify_webhook_signature,
)


@pytest.fixture
def invoice(db, django_user_model):
    user = django_user_model.objects.create_user(
        email="coll@test.tg", password="Monexa2026!", role="CAISSIER"
    )
    return Invoice.objects.create(
        reference="FACT-2026-9001",
        client_name="Boutique Adjo",
        client_phone="+228 90 12 34 56",
        amount=Decimal("25000"),
        issue_date=timezone.localdate(),
        due_date=timezone.localdate(),
        created_by=user,
    )


def test_sandbox_by_default(db, invoice, django_user_model):
    user = django_user_model.objects.create_user(
        email="ger@monexa.tg", password="Monexa2026!", role="GERANT"
    )
    assert not is_live("TMONEY")
    gt = request_collection(invoice, "TMONEY", "90123456", user)
    assert gt.is_sandbox
    assert gt.status == GatewayTransactionStatus.PENDING
    assert gt.gateway_tx_id.startswith("SBTM-")
    assert gt.amount == Decimal("25000")


def test_sandbox_confirm_then_payment_created(db, invoice, django_user_model):
    user = django_user_model.objects.create_user(
        email="ger2@monexa.tg", password="Monexa2026!", role="GERANT"
    )
    gt = request_collection(invoice, "FLOOZ", "96888888", user)
    # Simulation de la validation client (créée il y a > 30 s → SUCCESS au check)
    backdated = timezone.now() - timezone.timedelta(seconds=60)
    GatewayTransaction.objects.filter(pk=gt.pk).update(created_at=backdated)
    gt.refresh_from_db()
    from finance.services.gateways import check_status

    check_status(gt)
    assert gt.status == GatewayTransactionStatus.SUCCESS
    payment = confirm_gateway_transaction(gt)
    assert payment is not None
    assert payment.provider_ref == f"GW{gt.gateway_tx_id}"
    assert payment.channel == "FLOOZ"
    # Idempotence : un second appel ne crée pas de doublon
    assert confirm_gateway_transaction(gt) == payment
    assert Payment.objects.filter(provider_ref=f"GW{gt.gateway_tx_id}").count() == 1


def test_webhook_signature():
    body = b'{"transactionId": "SBTM-1", "status": "SUCCESS"}'
    signature = hmac.new(
        settings.GATEWAY_WEBHOOK_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    assert verify_webhook_signature("TMONEY", body, signature)
    assert not verify_webhook_signature("TMONEY", body, "deadbeef")


def test_webhook_endpoint_rejects_bad_signature(client, db):
    url = reverse("gateway_webhook", kwargs={"operator": "tmoney"})
    resp = client.post(url, data=b"{}", content_type="application/json", HTTP_X_SIGNATURE="bad")
    assert resp.status_code == 401
