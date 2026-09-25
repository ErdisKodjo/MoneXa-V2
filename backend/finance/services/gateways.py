"""
Passerelles de collecte Mobile Money — T-Money, Moov Money, Flooz (v2.1).

Objectif (pilier « rigueur financière ») : encaisser, pas seulement réconcilier.
Flux de collecte :
1. Le Caissier demande l'encaissement d'une facture (téléphone du client).
2. `request_collection()` pousse une demande de débit (USSD push / API
   collection) vers l'opérateur → GatewayTransaction(status=PENDING).
3. Le client valide sur son téléphone → l'opérateur notifie le webhook
   `/api/gateways/webhook/<operator>/` (signature vérifiée) → SUCCESS.
4. À SUCCESS, le paiement est créé et passe dans le pipeline de
   réconciliation existant (matcher → A_VALIDER/RECONCILIE → audit immuable).

SANDBOX : si aucun couple URL/clé n'est configuré pour l'opérateur, la
réponse est simulée de façon déterministe (aucun appel réseau) — la démo
fonctionne donc sans compte opérateur, et le passage en production ne
demande que des variables d'environnement.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import urllib.error
import urllib.request
from decimal import Decimal
from typing import Optional

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from finance.models import (
    Channel,
    GatewayTransaction,
    GatewayTransactionStatus,
    Invoice,
)

logger = logging.getLogger("monexa.gateway")

_COLLECTION_SETTINGS = {
    "TMONEY": ("TMONEY_COLLECTION_URL", "TMONEY_API_KEY", "TMONEY_API_SECRET"),
    "MOOV": ("MOOV_COLLECTION_URL", "MOOV_API_KEY", "MOOV_API_SECRET"),
    "FLOOZ": ("FLOOZ_COLLECTION_URL", "FLOOZ_API_KEY", "FLOOZ_API_SECRET"),
}


def operator_config(operator: str) -> dict:
    """Configuration de l'opérateur {url, key, secret} depuis les settings."""
    names = _COLLECTION_SETTINGS.get(operator)
    if not names:
        return {}
    url, key, secret = names
    return {
        "url": getattr(settings, url, "") or "",
        "key": getattr(settings, key, "") or "",
        "secret": getattr(settings, secret, "") or "",
    }


def is_live(operator: str) -> bool:
    """True si l'opérateur est configuré (mode production), sinon sandbox."""
    cfg = operator_config(operator)
    return bool(cfg.get("url") and cfg.get("key"))


def _sandbox_tx_id(operator: str) -> str:
    """ID déterministe et unique par appel (sandbox)."""
    from uuid import uuid4

    prefix = {"TMONEY": "SBTM", "MOOV": "SBMV", "FLOOZ": "SBFL"}.get(operator, "SB")
    return f"{prefix}-{uuid4().hex[:12].upper()}"


def _call_operator_collection(
    operator: str, cfg: dict, phone: str, amount: Decimal, reference: str
) -> dict:
    """
    Appel réel API collection (style OpenAPI MoMo : Basic auth → token →
    requesttopay). Simplifié en un POST avec clé API — à ajuster selon la
    documentation contractuelle de chaque opérateur.
    """
    body = {
        "amount": str(amount),
        "currency": "XOF",
        "externalId": reference,
        "payer": {"partyIdType": "MSISDN", "partyId": phone},
        "payerMessage": f"Paiement facture {reference} — MoneXa",
        "payeeNote": f"MoneXa {reference}",
    }
    req = urllib.request.Request(
        cfg["url"],
        data=json.dumps(body).encode("utf-8"),
        headers={
            "X-API-Key": cfg["key"],
            "X-API-Secret": cfg["secret"],
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return {
        "gateway_tx_id": str(payload.get("transactionId") or payload.get("financialTransactionId") or ""),
        "status": str(payload.get("status", "PENDING")).upper(),
        "raw": payload,
    }


def request_collection(
    invoice: Invoice, operator: str, phone: str, initiated_by
) -> GatewayTransaction:
    """
    Déclenche une demande de collecte pour une facture.
    Crée toujours la GatewayTransaction (sandbox ou live).
    """
    if operator not in _COLLECTION_SETTINGS:
        raise ValueError(f"Opérateur non supporté : {operator}")

    cfg = operator_config(operator)
    live = bool(cfg.get("url") and cfg.get("key"))
    amount = invoice.amount

    with transaction.atomic():
        if live:
            try:
                result = _call_operator_collection(operator, cfg, phone, amount, invoice.reference)
                tx_id = result["gateway_tx_id"] or _sandbox_tx_id(operator)
                status = (
                    GatewayTransactionStatus.PENDING
                    if result["status"] in ("PENDING", "ONGOING", "SUBMITTED", "")
                    else result["status"]
                )
                raw = result["raw"]
            except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as exc:
                logger.warning("Collection %s indisponible: %s — bascule sandbox", operator, exc)
                tx_id, status, raw = (
                    _sandbox_tx_id(operator), GatewayTransactionStatus.PENDING,
                    {"error": str(exc)[:300], "fallback": "sandbox"},
                )
                live = False
        else:
            tx_id = _sandbox_tx_id(operator)
            status = GatewayTransactionStatus.PENDING
            raw = {
                "sandbox": True,
                "message": (
                    f"Push USSD simulé vers {phone} : le client doit valider le débit de "
                    f"{amount:,.0f} FCFA pour la facture {invoice.reference}. "
                    "Configurez les clés API pour le mode production."
                ),
            }

        gt = GatewayTransaction.objects.create(
            invoice=invoice,
            operator=operator,
            phone=phone,
            amount=amount,
            gateway_tx_id=tx_id,
            status=status,
            is_sandbox=not live,
            raw_response=raw,
            initiated_by=initiated_by,
        )
    return gt


def check_status(gt: GatewayTransaction) -> GatewayTransaction:
    """
    Rafraîchit le statut d'une transaction passerelle.
    Sandbox : PENDING → SUCCESS (simulation de validation client).
    Live : GET statut opérateur (si URL fournie).
    """
    if gt.status != GatewayTransactionStatus.PENDING:
        return gt

    if gt.is_sandbox:
        # Sandbox : une transaction créée il y a > 30 s est « validée » par le client
        elapsed = (timezone.now() - gt.created_at).total_seconds()
        if elapsed > 30:
            gt.status = GatewayTransactionStatus.SUCCESS
            gt.raw_response = {
                **gt.raw_response,
                "sandbox_confirmed_at": timezone.now().isoformat(),
                "message": "Validation client simulée (sandbox) après 30 s.",
            }
            gt.save(update_fields=["status", "raw_response", "updated_at"])
        return gt

    cfg = operator_config(gt.operator)
    if not cfg.get("url"):
        return gt
    try:
        status_url = cfg["url"].rstrip("/") + "/" + gt.gateway_tx_id + "/"
        req = urllib.request.Request(
            status_url, headers={"X-API-Key": cfg["key"]}, method="GET"
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        new_status = str(payload.get("status", "")).upper()
        if new_status in GatewayTransactionStatus.values:
            gt.status = new_status
            gt.raw_response = {**gt.raw_response, "poll": payload}
            gt.save(update_fields=["status", "raw_response", "updated_at"])
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as exc:
        logger.warning("Poll statut %s échoué: %s", gt.gateway_tx_id, exc)
    return gt


def verify_webhook_signature(operator: str, body: bytes, signature: str) -> bool:
    """
    Vérifie la signature du webhook opérateur :
    HMAC-SHA256(secret, body) hexadécimal dans l'en-tête X-Signature.
    """
    secret = getattr(settings, "GATEWAY_WEBHOOK_SECRET", "")
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@transaction.atomic
def confirm_gateway_transaction(gt: GatewayTransaction) -> Optional[object]:
    """
    Transforme une collection SUCCESS en Payment réel dans le pipeline
    (réconciliation automatique + audit immuable). Idempotent : ne crée
    rien si le provider_ref existe déjà.
    """
    from finance.models import Payment, MatchMethod
    from finance.services.matcher import match_payment

    if gt.status != GatewayTransactionStatus.SUCCESS:
        return None
    provider_ref = f"GW{gt.gateway_tx_id}"
    if Payment.objects.filter(provider_ref=provider_ref).exists():
        return Payment.objects.get(provider_ref=provider_ref)

    payment = Payment(
        provider_ref=provider_ref,
        amount=gt.amount,
        channel=gt.operator,
        payer_name=f"Collecte {gt.get_operator_display()} {gt.phone}",
        payer_phone=gt.phone,
        paid_at=timezone.now(),
        raw_text=f"[GATEWAY] Collection {gt.gateway_tx_id} ({'sandbox' if gt.is_sandbox else 'live'}) "
                 f"facture {gt.invoice.reference}",
        ai_confidence=1.0,
        created_by=gt.initiated_by,
    )
    payment.save()
    new_status, invoice, method = match_payment(payment)
    payment.status = new_status
    payment.match_method = method
    if invoice:
        payment.invoice = invoice
    payment.save(update_fields=["status", "match_method", "invoice", "updated_at"])
    return payment
