"""
Relances automatiques de factures impayées (v2.3 — feature Tier 2 du README).

Principe (aligné sur TresorIA §12.1) :
- Les données factuelles (facture, échéance, montant) sont calculées côté
  serveur ; le LLM ne fait que RÉDIGER le message de relance.
- Sans clé API (ou en pytest), un template déterministe prend le relais —
  la démo hors-ligne reste garantie.
- Une seule notification par facture et par jour (anti-spam).
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import timedelta
from typing import Optional

from django.utils import timezone

from finance.models import Invoice

logger = logging.getLogger("monexa.relances")

JOURS_APRES_ECHEANCE = 7


def _setting(name: str, default: str = "") -> str:
    try:
        from django.conf import settings
        value = getattr(settings, name, None)
        if value:
            return str(value)
    except Exception:
        pass
    return os.environ.get(name, default) or default


def overdue_invoices(days: int = JOURS_APRES_ECHEANCE):
    """
    Factures EN_ATTENTE échues depuis plus de `days` jours,
    triées de la plus ancienne à la plus récente.
    """
    limite = timezone.localdate() - timedelta(days=days)
    return list(
        Invoice.objects.filter(status="EN_ATTENTE", due_date__lt=limite).order_by(
            "due_date"
        )
    )


def _template_message(invoice, jours_retard: int) -> str:
    """Relance déterministe — utilisée hors-ligne et comme fallback."""
    montant = f"{int(invoice.amount):,} FCFA".replace(",", " ")
    return (
        f"Bonjour {invoice.client_name}, "
        f"la facture {invoice.reference} d'un montant de {montant} "
        f"(échéance du {invoice.due_date:%d/%m/%Y}) est en attente de règlement "
        f"depuis {jours_retard} jour(s). "
        f"Merci de régler via T-Money (*880#), Moov Money (*155#) ou Flooz (*110#) "
        f"en mentionnant la référence {invoice.reference}. "
        "Votre confiance est précieuse — l'équipe MoneXa reste à votre disposition."
    )


def _relance_prompt(invoice, jours_retard: int) -> str:
    montant = f"{int(invoice.amount):,}".replace(",", " ")
    return (
        "Tu es l'assistant CFO de MoneXa. Rédige un message de relance pour une "
        "facture impayée : courtois, ferme, court (3 phrases max), en français, "
        "prêt à envoyer par SMS ou WhatsApp.\n"
        f"Client : {invoice.client_name}\n"
        f"Référence facture : {invoice.reference}\n"
        f"Montant : {montant} FCFA\n"
        f"Échéance : {invoice.due_date:%d/%m/%Y} (retard de {jours_retard} jours)\n"
        f"Jours de retard : {jours_retard}\n"
        "Moyens de paiement : T-Money *880#, Moov Money *155#, Flooz *110#, "
        f"référence {invoice.reference} dans le motif.\n"
        "N'invente aucun chiffre hors de ceux fournis."
    )


def _call_llm_relance(prompt: str) -> Optional[str]:
    """LLM réel si clé configurée ; None sinon / en pytest / en cas d'erreur."""
    if "pytest" in sys.modules and not os.environ.get("FORCE_REAL_LLM"):
        return None
    import json
    import urllib.request

    try:
        timeout = int(_setting("TREASORIA_LLM_TIMEOUT", "12"))
    except ValueError:
        timeout = 12

    openai_key = _setting("OPENAI_API_KEY")
    if openai_key.strip():
        try:
            body = {
                "model": _setting("OPENAI_VISION_MODEL", os.environ.get("OPENAI_VISION_MODEL", "gpt-4o-mini")),
                "temperature": 0.4,
                "max_tokens": 180,
                "messages": [{"role": "user", "content": prompt}],
            }
            req = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions",
                data=json.dumps(body).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {openai_key.strip()}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
            if content and content.strip():
                return content.strip()
        except Exception as exc:
            logger.warning("Relance LLM OpenAI indisponible : %s", exc)

    gemini_key = _setting("GEMINI_API_KEY")
    if gemini_key.strip():
        try:
            body = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.4, "maxOutputTokens": 180},
            }
            model = _setting("GEMINI_VISION_MODEL", os.environ.get("GEMINI_VISION_MODEL", "gemini-2.0-flash"))
            req = urllib.request.Request(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={gemini_key.strip()}",
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            content = data["candidates"][0]["content"]["parts"][0]["text"]
            if content and content.strip():
                return content.strip()
        except Exception as exc:
            logger.warning("Relance LLM Gemini indisponible : %s", exc)

    return None


def build_reminder_message(invoice, use_llm: bool = True) -> tuple[str, str]:
    """
    Message de relance pour une facture.
    Retourne (message, source) où source ∈ {"LLM", "TEMPLATE"}.
    """
    jours_retard = max(1, (timezone.localdate() - invoice.due_date).days)
    if use_llm:
        msg = _call_llm_relance(_relance_prompt(invoice, jours_retard))
        if msg:
            return msg, "LLM"
    return _template_message(invoice, jours_retard), "TEMPLATE"


def create_reminders(days: int = JOURS_APRES_ECHEANCE, dry_run: bool = False) -> list[dict]:
    """
    Crée une notification RAPPEL_FACTURE pour chaque Gérant et Comptable
    pour chaque facture impayée de plus de `days` jours.
    Anti-spam : 1 seule relance par facture et par jour (dédup sur titre).

    Retourne une liste [{invoice, message, source}].
    """
    from accounts.models import Notification, Role, User

    factures = overdue_invoices(days=days)
    if not factures:
        return []

    destinataires = list(
        User.objects.filter(role__in=[Role.GERANT, Role.COMPTABLE], is_active=True)
    )
    today = timezone.localdate()
    created = []

    for inv in factures:
        message, source = build_reminder_message(inv, use_llm=True)
        titre = f"Relance {inv.reference} — {today:%d/%m/%Y}"
        if dry_run:
            created.append({"invoice": inv, "message": message, "source": source})
            continue
        if Notification.objects.filter(kind="RAPPEL_FACTURE", title=titre).exists():
            continue
        first_dest = destinataires[0] if destinataires else None
        if first_dest is None:
            break
        for user in destinataires:
            Notification.objects.create(
                user=user,
                kind="RAPPEL_FACTURE",
                title=titre,
                body=message,
                url="/factures/",
            )
        created.append({"invoice": inv, "message": message, "source": source})

    logger.info("Relances générées : %d facture(s)", len(created))
    return created
