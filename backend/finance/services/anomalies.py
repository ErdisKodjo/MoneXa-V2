"""
Détection d'anomalies hybride (cahier des charges §13.2):

1. Règles déterministes (temps réel):
   - Doublon de provider_ref (renvoyé par la contrainte DB UNIQUE)
   - Écart facture / paiement (montant payé != montant facturé)
   - Paiement sans facture (NON_RATTACHE)
   - Paiement hors fenêtre temporelle (date paiement < date facture)
2. Scoring ML (batch) — Isolation Forest sur 90 jours d'historique
   - Paiements atypiques (montant inhabituel, horaire inhabituel, canal inhabituel)
"""
from __future__ import annotations
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from decimal import Decimal

from finance.models import Payment, Invoice, PaymentStatus


SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"


def detect_anomalies(payment: Payment) -> List[dict]:
    """
    Run all rule-based anomaly checks on a payment.

    Returns:
        list of dicts: [
            {"severity": "critical", "type": "Doublon provider_ref",
             "description": "...", "payment_id": payment.id},
            ...
        ]
    """
    anomalies: List[dict] = []
    now = datetime.now(timezone.utc)

    # Rule 1 — Écart facture / paiement
    if payment.invoice_id:
        try:
            invoice = payment.invoice
            if invoice.amount != payment.amount:
                ecart = abs(invoice.amount - payment.amount)
                anomalies.append({
                    "severity": SEVERITY_WARNING,
                    "type": "Écart facture / paiement",
                    "description": (
                        f"{invoice.reference} — facturé {invoice.amount:,.2f} FCFA, "
                        f"payé {payment.amount:,.2f} FCFA (écart {ecart:,.2f})"
                    ),
                    "payment_id": payment.id,
                })
        except Invoice.DoesNotExist:
            pass

    # Rule 2 — Paiement sans facture (NON_RATTACHE)
    if payment.status == PaymentStatus.NON_RATTACHE or not payment.invoice_id:
        if not payment.invoice_id:
            anomalies.append({
                "severity": SEVERITY_WARNING,
                "type": "Paiement sans facture",
                "description": (
                    f"{payment.provider_ref} — paiement non rattaché à une facture"
                ),
                "payment_id": payment.id,
            })

    # Rule 3 — Paiement hors fenêtre temporelle (avant la facture)
    if payment.invoice_id:
        try:
            invoice = payment.invoice
            if payment.paid_at.date() < invoice.issue_date:
                anomalies.append({
                    "severity": SEVERITY_CRITICAL,
                    "type": "Paiement hors fenêtre temporelle",
                    "description": (
                        f"{payment.provider_ref} — paiement le "
                        f"{payment.paid_at:%Y-%m-%d} antérieur à la facture "
                        f"{invoice.reference} émise le {invoice.issue_date:%Y-%m-%d}"
                    ),
                    "payment_id": payment.id,
                })
        except Invoice.DoesNotExist:
            pass

    # Rule 4 — Paiement nocturne (heuristique: entre 22h et 06h = suspect)
    hour_local = payment.paid_at.hour
    if 22 <= hour_local or hour_local < 6:
        anomalies.append({
            "severity": SEVERITY_INFO,
            "type": "Paiement nocturne",
            "description": (
                f"{payment.provider_ref} — paiement effectué à "
                f"{payment.paid_at:%H:%M} (heures non habituelles)"
            ),
            "payment_id": payment.id,
        })

    anomalies.extend(_detect_fraud_rules(payment))
    return anomalies


# ──────────────────────────────────────────────────────────────────────────
# Règles anti-fraude SMS (v2.1) — numéros usurpés, refs falsifiées, rafales
# ──────────────────────────────────────────────────────────────────────────

# Préfixes opérateurs Togo (+228) — surchargeables via MONEXA_OPERATOR_PREFIXES
DEFAULT_OPERATOR_PREFIXES = {
    "TMONEY": ("90", "91", "92", "93"),
    "MOOV": ("94", "95"),
    "FLOOZ": ("96", "97"),
}

_PHISHING_KEYWORDS = (
    "pin", "code secret", "otp", "mot de passe",
    "envoyez votre", "transferez", "transfère", "envoyer l'argent",
    "urgent", "compte bloqué", "compte bloque", "gagner", "loterie",
)


def _operator_prefixes() -> dict:
    """Mapping canal → préfixes valides (settings surcharge possible)."""
    from django.conf import settings

    return getattr(settings, "MONEXA_OPERATOR_PREFIXES", DEFAULT_OPERATOR_PREFIXES)


def _detect_fraud_rules(payment: Payment) -> List[dict]:
    anomalies: List[dict] = []

    phone_digits = re.sub(r"\D", "", payment.payer_phone or "")
    # Numéro local à 8 chiffres (on ignore l'indicatif +228)
    if len(phone_digits) > 8:
        phone_digits = phone_digits[-8:]
    local_prefix = phone_digits[:2]

    # Rule 5 — Numéro émetteur incompatible avec le canal déclaré
    prefixes = _operator_prefixes()
    if payment.channel in prefixes and local_prefix:
        valid = prefixes[payment.channel]
        if local_prefix not in valid:
            anomalies.append({
                "severity": SEVERITY_WARNING,
                "type": "Numéro incompatible avec le canal",
                "description": (
                    f"{payment.provider_ref} — payeur {payment.payer_phone} mais canal "
                    f"{payment.get_channel_display()} (préfixes attendus : {', '.join(valid)})"
                ),
                "payment_id": payment.id,
            })

    # Rule 6 — Référence opérateur falsifiée (préfixe de référence ≠ canal)
    ref_prefixes = {"TMONEY": "TMX", "MOOV": ("MV", "MP"), "FLOOZ": "FL"}
    expected = ref_prefixes.get(payment.channel)
    if expected:
        ref = (payment.provider_ref or "").upper()
        if ref and not ref.startswith(tuple(expected)):
            anomalies.append({
                "severity": SEVERITY_WARNING,
                "type": "Référence suspecte",
                "description": (
                    f"{payment.provider_ref} — le format de la référence ne correspond "
                    f"pas au canal {payment.get_channel_display()} (attendu : {'/'.join(expected)})"
                ),
                "payment_id": payment.id,
            })

    # Rule 7 — Rafale de paiements du même émetteur (≥3 en 10 minutes)
    if payment.payer_phone:
        window_start = payment.paid_at - timedelta(minutes=10)
        window_end = payment.paid_at + timedelta(minutes=10)
        burst = Payment.objects.filter(
            payer_phone=payment.payer_phone,
            paid_at__gte=window_start,
            paid_at__lte=window_end,
        ).exclude(pk=payment.pk).count()
        if burst >= 2:
            anomalies.append({
                "severity": SEVERITY_CRITICAL,
                "type": "Rafale de paiements",
                "description": (
                    f"{payment.provider_ref} — {burst + 1} paiements du même numéro "
                    f"{payment.payer_phone} en moins de 10 minutes (fraude / cash-out suspect)"
                ),
                "payment_id": payment.id,
            })

    # Rule 8 — SMS d'hameçonnage (mots-clés frauduleux dans le texte extrait)
    raw = (payment.raw_text or "").lower()
    if raw and any(kw in raw for kw in _PHISHING_KEYWORDS):
        hit = next(kw for kw in _PHISHING_KEYWORDS if kw in raw)
        anomalies.append({
            "severity": SEVERITY_CRITICAL,
            "type": "SMS suspect (hameçonnage)",
            "description": (
                f"{payment.provider_ref} — le texte contient le mot-clé sensible "
                f"« {hit} » : vérifier qu'il s'agit d'un SMS opérateur authentique"
            ),
            "payment_id": payment.id,
        })

    return anomalies


def scan_recent_fraud(limit: int = 200) -> List[dict]:
    """
    Scan anti-fraude des derniers paiements (tous statuts confondus).
    Utilisé par la page Anomalies pour attraper les fraudes détectées
    après ingestion (numéro usurpé, rafale, SMS hameçonnage…).
    """
    out: List[dict] = []
    seen_ids: set = set()
    for p in Payment.objects.order_by("-paid_at")[:limit]:
        for a in _detect_fraud_rules(p):
            key = (p.id, a.get("type", ""))
            if key not in seen_ids:
                seen_ids.add(key)
                out.append({
                    "payment": p,
                    "type": a.get("type", ""),
                    "description": a.get("description", ""),
                    "severity": a.get("severity", ""),
                })
    return out


def score_isolation_forest() -> List[dict]:
    """
    Batch ML scoring — Isolation Forest on 90 days of payments.

    Returns:
        list of {payment_id, score, flagged} for payments with score > 0.7.
    """
    from sklearn.ensemble import IsolationForest
    import numpy as np

    payments = list(Payment.objects.all().order_by("-paid_at")[:500])
    if len(payments) < 30:
        # Not enough data for ML
        return []

    # Features: amount (log), hour_of_day, channel_encoded
    X = []
    channel_map = {"TMONEY": 0, "MOOV": 1, "FLOOZ": 2, "BANQUE": 3, "ESPECES": 4}
    for p in payments:
        amount_log = float(np.log1p(float(p.amount)))
        hour = p.paid_at.hour
        channel_enc = channel_map.get(p.channel, 0)
        X.append([amount_log, hour, channel_enc])

    X_arr = np.array(X)
    clf = IsolationForest(contamination=0.05, random_state=42)
    clf.fit(X_arr)
    # decision_function: higher = more normal; negate so higher = more anomalous
    raw_scores = -clf.decision_function(X_arr)
    # Normalize to [0, 1]
    min_s, max_s = raw_scores.min(), raw_scores.max()
    if max_s > min_s:
        normalized = (raw_scores - min_s) / (max_s - min_s)
    else:
        normalized = raw_scores * 0

    flagged = []
    for p, score in zip(payments, normalized):
        if score > 0.7:
            flagged.append({
                "payment_id": p.id,
                "provider_ref": p.provider_ref,
                "score": float(score),
                "flagged": True,
            })

    return flagged
