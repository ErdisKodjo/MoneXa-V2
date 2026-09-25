"""Webhook opérateurs Mobile Money — confirmation de collecte (v2.1).

POST /api/gateways/webhook/<operator>/
- En-tête X-Signature : HMAC-SHA256(GATEWAY_WEBHOOK_SECRET, body) en hex.
- Payload attendu : {"transactionId": "...", "status": "SUCCESS|FAILED|EXPIRED"}.
- À SUCCESS : création du Payment (provider_ref GW<tx>) + réconciliation
  automatique + audit immuable — idempotent.
"""
from __future__ import annotations

import json
import logging

from django.http import JsonResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from finance.models import GatewayTransaction, GatewayTransactionStatus
from finance.services.gateways import confirm_gateway_transaction, verify_webhook_signature

logger = logging.getLogger("monexa.gateway")

_STATUS_MAP = {
    "SUCCESS": GatewayTransactionStatus.SUCCESS,
    "SUCCESSFUL": GatewayTransactionStatus.SUCCESS,
    "COMPLETED": GatewayTransactionStatus.SUCCESS,
    "FAILED": GatewayTransactionStatus.FAILED,
    "EXPIRED": GatewayTransactionStatus.EXPIRED,
}


@method_decorator(csrf_exempt, name="dispatch")
class GatewayWebhookView(View):
    """Webhook opérateur — signature HMAC obligatoire, traitement idempotent."""

    def post(self, request, operator: str):
        body = request.body or b""
        signature = request.headers.get("X-Signature", "")
        if not verify_webhook_signature(operator, body, signature):
            logger.warning("Webhook %s : signature invalide", operator)
            return JsonResponse({"error": "invalid signature"}, status=401)

        try:
            payload = json.loads(body.decode("utf-8") or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({"error": "invalid json"}, status=400)

        tx_id = str(payload.get("transactionId", ""))
        gt = GatewayTransaction.objects.filter(
            gateway_tx_id=tx_id, operator=operator.upper()
        ).first()
        if not gt:
            logger.warning("Webhook %s : transaction inconnue %s", operator, tx_id)
            return JsonResponse({"error": "unknown transaction"}, status=404)

        new_status = _STATUS_MAP.get(str(payload.get("status", "")).upper())
        if new_status:
            gt.status = new_status
            gt.raw_response = {**gt.raw_response, "webhook": payload}
            gt.save(update_fields=["status", "raw_response", "updated_at"])
        if gt.status == GatewayTransactionStatus.SUCCESS:
            payment = confirm_gateway_transaction(gt)
            return JsonResponse({
                "ok": True,
                "status": gt.status,
                "payment_created": payment is not None,
            })
        return JsonResponse({"ok": True, "status": gt.status})
