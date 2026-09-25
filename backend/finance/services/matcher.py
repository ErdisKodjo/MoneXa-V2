"""
Cascade de réconciliation automatique — 4 niveaux (cahier des charges §13.3):

1. AUTO_REF       : provider_ref contient la référence d'une facture (FACT-YYYY-XXXX)
                   → matching automatique, statut RECONCILIE
2. AUTO_MONTANT   : montant correspond à une facture impayée, date de paiement
                   dans la fenêtre de 7 jours après l'émission
                   → matching automatique, statut A_VALIDER (validation comptable)
3. FUZZY          : similarité > 0.8 entre nom du payeur ou téléphone et un client
                   avec facture impayée
                   → matching proposé, statut A_VALIDER
4. NON_RATTACHE   : aucune correspondance
                   → paiement en anomalie, statut NON_RATTACHE
"""
from __future__ import annotations
from datetime import timedelta
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Optional, Tuple

from finance.models import (
    Invoice, InvoiceStatus, MatchMethod, Payment, PaymentStatus,
)


def _similarity(a: str, b: str) -> float:
    """Return a similarity ratio between two strings (0..1)."""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _find_by_reference(payment: Payment) -> Optional[Invoice]:
    """
    Level 1 — référence facture présente dans provider_ref OU dans le
    libellé du payeur (cas des virements bancaires : « VIREMENT
    FACT-2026-0012 BTP PLUS » — v2.3 rapprochement multi-comptes).
    """
    haystack = f"{payment.provider_ref} {payment.payer_name}"
    candidates = Invoice.objects.filter(status=InvoiceStatus.EN_ATTENTE)
    for invoice in candidates:
        if invoice.reference and invoice.reference in haystack:
            return invoice
    return None


def _find_by_amount_and_date(payment: Payment) -> Optional[Invoice]:
    """Level 2 — exact amount match within 7 days after issue_date."""
    window_end = payment.paid_at.date() + timedelta(days=1)
    candidates = Invoice.objects.filter(
        status=InvoiceStatus.EN_ATTENTE,
        amount=payment.amount,
        issue_date__lte=payment.paid_at.date(),
        issue_date__gte=payment.paid_at.date() - timedelta(days=7),
    )
    return candidates.first()


def _find_by_fuzzy_payer(payment: Payment) -> Optional[Invoice]:
    """Level 3 — payer name/phone similarity > 0.8 with an invoice's client."""
    threshold = 0.8
    candidates = Invoice.objects.filter(status=InvoiceStatus.EN_ATTENTE)
    best_match: Optional[Invoice] = None
    best_score: float = 0.0

    for invoice in candidates:
        score_name = _similarity(payment.payer_name, invoice.client_name)
        score_phone = _similarity(payment.payer_phone, invoice.client_phone)
        score = max(score_name, score_phone)
        if score >= threshold and score > best_score:
            best_match = invoice
            best_score = score

    return best_match


def match_payment(payment: Payment) -> Tuple[PaymentStatus, Optional[Invoice], MatchMethod]:
    """
    Run the 4-level reconciliation cascade.

    Returns:
        (new_status, matched_invoice_or_None, match_method)
    """
    # Level 1 — exact reference
    invoice = _find_by_reference(payment)
    if invoice:
        return PaymentStatus.RECONCILIE, invoice, MatchMethod.AUTO_REF

    # Level 2 — amount + 7 days window
    invoice = _find_by_amount_and_date(payment)
    if invoice:
        return PaymentStatus.A_VALIDER, invoice, MatchMethod.AUTO_MONTANT

    # Level 3 — fuzzy payer
    invoice = _find_by_fuzzy_payer(payment)
    if invoice:
        return PaymentStatus.A_VALIDER, invoice, MatchMethod.FUZZY

    # Level 4 — no match
    return PaymentStatus.NON_RATTACHE, None, MatchMethod.MANUEL
