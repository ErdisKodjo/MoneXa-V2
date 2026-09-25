"""
Rapport hebdomadaire du CFO virtuel (v2.3 — feature Tier 2 du README).

Génère chaque semaine un rapport textuel pour le Gérant :
- Chiffres pré-calculés côté serveur via compute_kpis() (jamais de SQL LLM)
- Rédaction par LLM si clé API configurée, sinon synthèse déterministe
- Livré comme notification in-app aux Gérants + affichable via l'API

Aligné sur la règle §12.1 : le LLM reformule, il ne calcule pas.
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Optional

from django.utils import timezone

from reporting.services import compute_kpis

logger = logging.getLogger("monexa.rapport")


def _setting(name: str, default: str = "") -> str:
    try:
        from django.conf import settings
        value = getattr(settings, name, None)
        if value:
            return str(value)
    except Exception:
        pass
    return os.environ.get(name, default) or default


def _fmt_fcfa(amount) -> str:
    try:
        return f"{int(amount):,} FCFA".replace(",", " ")
    except (ValueError, TypeError):
        return "—"


def _weekly_facts() -> dict:
    """Chiffres factuels de la semaine — calculés côté serveur uniquement."""
    kpis = compute_kpis()
    start = timezone.now() - timezone.timedelta(days=7)
    return {
        "periode": f"{(start):%d/%m/%Y} → {timezone.now():%d/%m/%Y}",
        "encaisse_7j": kpis.get("encaisse_7j", 0),
        "decaisse_7j": kpis.get("decaisse_7j", 0),
        "solde_total": kpis.get("solde_total", 0),
        "flux_net_30j": kpis.get("flux_net_30j", 0),
        "factures_en_attente": kpis.get("factures_en_attente", 0),
        "factures_en_retard": kpis.get("factures_en_retard", 0),
        "paiements_a_valider": kpis.get("paiements_a_valider", 0),
        "nb_anomalies": kpis.get("nb_anomalies", 0),
        "prevision_j7": kpis.get("prevision_j7", 0),
        "prevision_j30": kpis.get("prevision_j30", 0),
        "top_clients": kpis.get("top_5_clients", []),
    }


def _facts_text(facts: dict) -> str:
    top = " ; ".join(
        f"{c['name']} ({_fmt_fcfa(c['total'])})" for c in facts.get("top_clients", [])[:3]
    )
    return "\n".join(
        [
            f"- Période : {facts['periode']}",
            f"- Encaissé 7 jours : {_fmt_fcfa(facts['encaisse_7j'])}",
            f"- Décaissé 7 jours : {_fmt_fcfa(facts['decaisse_7j'])}",
            f"- Solde total consolidé : {_fmt_fcfa(facts['solde_total'])}",
            f"- Flux net 30 jours : {_fmt_fcfa(facts['flux_net_30j'])}",
            f"- Factures en attente : {facts['factures_en_attente']} (dont {facts['factures_en_retard']} en retard)",
            f"- Paiements à valider : {facts['paiements_a_valider']}",
            f"- Anomalies en cours : {facts['nb_anomalies']}",
            f"- Prévision J+7 : {_fmt_fcfa(facts['prevision_j7'])} · J+30 : {_fmt_fcfa(facts['prevision_j30'])}",
            f"- Top clients : {top or 'aucun'}",
        ]
    )


def _template_report(facts: dict) -> str:
    """Synthèse déterministe — démo hors-ligne garantie."""
    net_7j = facts["encaisse_7j"] - facts["decaisse_7j"]
    sens = "excédent" if net_7j >= 0 else "déficit"
    alertes = []
    if facts["factures_en_retard"]:
        alertes.append(f"{facts['factures_en_retard']} facture(s) en retard de paiement")
    if facts["paiements_a_valider"]:
        alertes.append(f"{facts['paiements_a_valider']} paiement(s) à valider")
    if facts["nb_anomalies"]:
        alertes.append(f"{facts['nb_anomalies']} anomalie(s) à instruire")
    alerte_txt = ("Points d'attention : " + ", ".join(alertes) + ".") if alertes else (
        "Aucun point d'attention : opérations saines cette semaine."
    )
    return (
        f"Rapport hebdomadaire MoneXa — {facts['periode']}. "
        f"Encaissements {_fmt_fcfa(facts['encaisse_7j'])}, décaissements "
        f"{_fmt_fcfa(facts['decaisse_7j'])} : {sens} net de {_fmt_fcfa(net_7j)}. "
        f"Solde consolidé : {_fmt_fcfa(facts['solde_total'])}. "
        f"{alerte_txt} "
        f"Prévision Holt-Winters : {_fmt_fcfa(facts['prevision_j7'])} à J+7, "
        f"{_fmt_fcfa(facts['prevision_j30'])} à J+30."
    )


def _report_prompt(facts: dict) -> str:
    return (
        "Tu es le CFO virtuel MoneXa. Rédige un rapport hebdomadaire pour le "
        "dirigeant d'une PME ouest-africaine : 4 à 6 phrases maximum, français, "
        "ton professionnel, montants en FCFA formatés. Structure suggérée : "
        "bilan de la semaine, points d'attention, prévision, une recommandation "
        "actionnable.\n\nCHIFFRES DE LA SEMAINE (pré-calculés côté serveur) :\n"
        + _facts_text(facts)
        + "\n\nN'invente AUCUN chiffre : utilise uniquement ceux fournis."
    )


def _call_llm_report(prompt: str) -> Optional[str]:
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
                "temperature": 0.3,
                "max_tokens": 320,
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
            logger.warning("Rapport LLM OpenAI indisponible : %s", exc)

    gemini_key = _setting("GEMINI_API_KEY")
    if gemini_key.strip():
        try:
            body = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.3, "maxOutputTokens": 320},
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
            logger.warning("Rapport LLM Gemini indisponible : %s", exc)

    return None


def generate_weekly_report(use_llm: bool = True) -> tuple[str, str]:
    """
    Rapport hebdo : (texte, source) où source ∈ {"LLM", "TEMPLATE"}.
    """
    facts = _weekly_facts()
    if use_llm:
        text = _call_llm_report(_report_prompt(facts))
        if text:
            return text, "LLM"
    return _template_report(facts), "TEMPLATE"


def deliver_weekly_report() -> tuple[str, str]:
    """
    Génère le rapport et le livre en notification INFO à chaque Gérant.
    Retourne (texte, source).
    """
    from accounts.models import Notification, Role, User

    text, source = generate_weekly_report(use_llm=True)
    periode = _weekly_facts()["periode"]
    gérants = User.objects.filter(role=Role.GERANT, is_active=True)
    for user in gérants:
        Notification.objects.create(
            user=user,
            kind="INFO",
            title=f"Rapport hebdomadaire CFO — {periode}",
            body=text,
            url="/dashboard/",
        )
    logger.info("Rapport hebdo livré (%s) à %d gérant(s)", source, gérants.count())
    return text, source
