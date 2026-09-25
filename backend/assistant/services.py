"""
TresorIA — CFO virtuel en langage naturel.

RÈGLE FONDAMENTALE (cahier des charges §12.1):
- Le LLM ne génère JAMAIS de SQL.
- Le LLM n'a JAMAIS accès à la base.
- Le backend pré-calcule 15 KPIs et les injecte dans le contexte.
- Le LLM ne fait que reformuler les KPIs en langage naturel.

Ici, en mode démo (pas de clé OpenAI), on simule le LLM via un moteur
de règles qui pattern-matche la question et répond avec les KPIs.
"""
from __future__ import annotations
import logging
import os
import re
import sys
from typing import Optional

from reporting.services import compute_kpis

logger = logging.getLogger("monexa.tresoria")


def _setting(name: str, default: str = "") -> str:
    """Read from Django settings (.env) then process env."""
    try:
        from django.conf import settings
        value = getattr(settings, name, None)
        if value:
            return str(value)
    except Exception:
        pass
    return os.environ.get(name, default) or default


def _format_fcfa(amount: float) -> str:
    """Format a number as FCFA: '1 250 000 FCFA'."""
    try:
        return f"{int(amount):,} FCFA".replace(",", " ")
    except (ValueError, TypeError):
        return "—"


# ────────────────────────────────────────────────────────────────────────
# Niveau 1 — LLM réel (clé API présente) : reformulation des KPIs.
# RÈGLE FONDAMENTALE §12.1 : le LLM ne reçoit QUE les KPIs pré-calculés,
# jamais d'accès DB, jamais de SQL. Fallback automatique → moteur de règles.
# ────────────────────────────────────────────────────────────────────────

_TRESORIA_SYSTEM_PROMPT = """Tu es TresorIA, le CFO virtuel de MoneXa, une PME ouest-africaine.
RÈGLES ABSOLUES :
- Tu réponds UNIQUEMENT à partir des KPIs fournis ci-dessous.
- N'invente JAMAIS un chiffre qui ne figure pas dans les KPIs.
- Jamais de SQL, jamais de mention technique de base de données.
- Réponse en français, maximum 3 phrases, ton professionnel et chaleureux.
- Montants en FCFA formatés (ex: 1 250 000 FCFA).
- Si la question dépasse les KPIs fournis, redirige vers une question possible."""


def _serialize_kpis(kpis: dict) -> str:
    """Sérialise les KPIs pré-calculés en texte injectable dans le prompt LLM."""
    canaux = kpis.get("solde_par_canal", {})
    canaux_str = " ; ".join(f"{c}={_format_fcfa(v)}" for c, v in canaux.items() if v)
    lignes = [
        f"- Solde total consolidé : {_format_fcfa(kpis.get('solde_total', 0))}",
        f"- Soldes par canal : {canaux_str or 'aucun'}",
        f"- Encaissé 7 jours : {_format_fcfa(kpis.get('encaisse_7j', 0))}",
        f"- Encaissé 30 jours : {_format_fcfa(kpis.get('encaisse_30j', 0))}",
        f"- Décaissé 7 jours : {_format_fcfa(kpis.get('decaisse_7j', 0))}",
        f"- Décaissé 30 jours : {_format_fcfa(kpis.get('decaisse_30j', 0))}",
        f"- Flux net 30 jours : {_format_fcfa(kpis.get('flux_net_30j', 0))}",
        f"- Factures en attente : {kpis.get('factures_en_attente', 0)}",
        f"- Factures en retard : {kpis.get('factures_en_retard', 0)}",
        f"- Paiements à valider : {kpis.get('paiements_a_valider', 0)}",
        f"- Anomalies en cours : {kpis.get('nb_anomalies', 0)}",
        f"- Prévision trésorerie J+7 : {_format_fcfa(kpis.get('prevision_j7', 0))}",
        f"- Prévision trésorerie J+30 : {_format_fcfa(kpis.get('prevision_j30', 0))}",
    ]
    top = kpis.get("top_5_clients") or []
    if top:
        clients = " ; ".join(
            f"{c['name']} ({_format_fcfa(c['total'])}, {c['count']} paiements)"
            for c in top[:5]
        )
        lignes.append(f"- Top clients : {clients}")
    return "\n".join(lignes)


def _build_llm_prompt(question: str, kpis: dict) -> str:
    """Construit le prompt : règles + KPIs + question. Aucun accès DB côté LLM."""
    return (
        _TRESORIA_SYSTEM_PROMPT
        + "\n\nKPIs TRÉSORERIE (pré-calculés côté serveur) :\n"
        + _serialize_kpis(kpis)
        + f"\n\nQuestion du dirigeant : « {question.strip()} »"
    )


def _call_llm_cfo(question: str, kpis: dict) -> Optional[str]:
    """
    Appelle OpenAI (gpt-4o-mini) ou Gemini Flash avec les KPIs injectés.
    Le LLM ne fait que REFORMULER — jamais de SQL, jamais d'accès DB.
    Retourne None si pas de clé, timeout ou erreur → fallback moteur de règles.
    """
    # Garde pytest : déterminisme des tests sans réseau (même règle que ai_pipeline)
    if "pytest" in sys.modules and not os.environ.get("FORCE_REAL_LLM"):
        return None
    import json as _json
    import urllib.request

    prompt = _build_llm_prompt(question, kpis)
    try:
        timeout = int(_setting("TREASORIA_LLM_TIMEOUT", "12"))
    except ValueError:
        timeout = 12

    openai_key = _setting("OPENAI_API_KEY")
    if openai_key.strip():
        try:
            body = {
                "model": _setting(
                    "OPENAI_VISION_MODEL",
                    os.environ.get("OPENAI_VISION_MODEL", "gpt-4o-mini"),
                ),
                "temperature": 0.2,
                "max_tokens": 250,
                "messages": [{"role": "user", "content": prompt}],
            }
            req = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions",
                data=_json.dumps(body).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {openai_key.strip()}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
            if content and content.strip():
                return content.strip()
        except Exception as exc:
            logger.warning("TresorIA LLM OpenAI indisponible: %s", exc)

    gemini_key = _setting("GEMINI_API_KEY")
    if gemini_key.strip():
        try:
            model = _setting(
                "GEMINI_VISION_MODEL",
                os.environ.get("GEMINI_VISION_MODEL", "gemini-2.0-flash"),
            )
            url = (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent?key={gemini_key.strip()}"
            )
            body = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.2, "maxOutputTokens": 250},
            }
            req = urllib.request.Request(
                url,
                data=_json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
            content = data["candidates"][0]["content"]["parts"][0]["text"]
            if content and content.strip():
                return content.strip()
        except Exception as exc:
            logger.warning("TresorIA LLM Gemini indisponible: %s", exc)
    return None


def answer_question(user, question: str) -> str:
    """
    Generate an answer from the TresorIA chatbot.

    Args:
        user: the authenticated User
        question: the question in natural language (FR)

    Returns:
        A natural-language answer string.
    """
    if not question or len(question.strip()) < 3:
        return (
            "Je n'ai pas bien compris votre question. "
            "Essayez : \"Combien ai-je en T-Money ?\", "
            "\"Quelle est ma trésorerie à 30 jours ?\", "
            "\"Combien d'anomalies ?\" ou "
            "\"Quelles factures sont en retard ?\"."
        )

    q = question.lower().strip()
    kpis = compute_kpis()

    # Niveau 1 — LLM réel si clé API configurée (KPIs injectés, jamais de SQL)
    if _setting("TREASORIA_USE_LLM", "1").strip().lower() in ("1", "true", "yes", "on"):
        llm_answer = _call_llm_cfo(question, kpis)
        if llm_answer:
            return llm_answer

    # Niveau 2 — moteur de règles déterministe (démo hors-ligne / fallback)

    # ── Pattern matching ────────────────────────────────────────────

    # Solde T-Money
    if re.search(r"(tmoney|t-money|t money)", q) and re.search(r"(solde|combien|montant)", q):
        solde = kpis["solde_par_canal"].get("TMONEY", 0)
        return (
            f"Votre solde T-Money actuel est de {_format_fcfa(solde)}. "
            f"C'est le canal qui représente la part la plus importante de votre trésorerie mobile."
        )

    # Solde Moov
    if re.search(r"(moov)", q) and re.search(r"(solde|combien|montant)", q):
        solde = kpis["solde_par_canal"].get("MOOV", 0)
        return f"Votre solde Moov Money actuel est de {_format_fcfa(solde)}."

    # Solde Flooz
    if re.search(r"(flooz)", q) and re.search(r"(solde|combien|montant)", q):
        solde = kpis["solde_par_canal"].get("FLOOZ", 0)
        return f"Votre solde Flooz actuel est de {_format_fcfa(solde)}."

    # Solde total
    if re.search(r"(solde total|combien.*total|trésorerie.*actuelle|tous.*canaux)", q):
        return (
            f"Votre trésorerie totale consolidée est de {_format_fcfa(kpis['solde_total'])}, "
            f"répartie sur tous vos canaux Mobile Money et bancaires."
        )

    # Encaissé 7j / semaine
    if re.search(r"(encaissé|encaisse|recette).*semaine|semaine.*(encaissé|encaisse|recette)", q) \
       or re.search(r"(7.*jour|cette semaine)", q):
        tmoney_share = kpis["solde_par_canal"].get("TMONEY", 0)
        total_solde = kpis["solde_total"] or 1
        tmoney_part = (tmoney_share / total_solde) * 100 if total_solde > 0 else 0
        return (
            f"Cette semaine (7 derniers jours), vous avez encaissé {_format_fcfa(kpis['encaisse_7j'])}. "
            f"Le canal T-Money représente {tmoney_part:.1f}% de votre trésorerie globale."
        )

    # Encaissé 30j / mois
    if re.search(r"(encaissé|encaisse|recette).*(mois|30.*jour)|mois.*(encaissé|encaisse)", q) \
       or re.search(r"30.*jour", q) and "enca" in q:
        return (
            f"Sur les 30 derniers jours, vous avez encaissé {_format_fcfa(kpis['encaisse_30j'])} "
            f"et décaissé {_format_fcfa(kpis['decaisse_30j'])}, "
            f"soit un flux net de {_format_fcfa(kpis['flux_net_30j'])}."
        )

    # Prévisions / trésorerie 30 jours
    if re.search(r"(prévision|prevision|trésorerie.*30|j\+30|projection|future|avenir)", q):
        return (
            f"À J+30, votre trésorerie projetée est de {_format_fcfa(kpis['prevision_j30'])} "
            f"(modèle Holt-Winters, lissage exponentiel triple). "
            f"La prévision à court terme (J+7) est de {_format_fcfa(kpis['prevision_j7'])}."
        )

    # Anomalies
    if re.search(r"(anomalie|fraude|doublon|écart|probleme|problème)", q):
        return (
            f"Vous avez {kpis['nb_anomalies']} anomalie(s) en cours. "
            f"Pour les consulter en détail, accédez à la section Anomalies (réservée au Gérant). "
            f"Les paiements en anomalie nécessitent une résolution manuelle."
        )

    # Factures en retard
    if re.search(r"(facture.*retard|retard.*facture|impayée|impayee|en retard)", q):
        return (
            f"{kpis['factures_en_retard']} facture(s) sont en retard de paiement. "
            f"Vous avez {kpis['factures_en_attente']} facture(s) en attente au total. "
            f"Pensez à relancer les clients avec des factures en retard."
        )

    # Top 5 clients
    if re.search(r"(top.*client|meilleur.*client|client.*fidèle|fidele)", q):
        if kpis["top_5_clients"]:
            lines = []
            for i, c in enumerate(kpis["top_5_clients"][:5], 1):
                lines.append(f"{i}. {c['name']} — {_format_fcfa(c['total'])} sur {c['count']} paiement(s)")
            return "Vos 5 meilleurs clients sont :\n" + "\n".join(lines)
        return "Aucun paiement n'a encore été enregistré."

    # Paiements à valider
    if re.search(r"(valider|à valider|a valider|file.*validation|en attente.*paiement)", q):
        return (
            f"{kpis['paiements_a_valider']} paiement(s) sont en attente de validation "
            f"par le comptable. Connectez-vous avec un compte Comptable ou Gérant pour les valider."
        )

    # Bonjour / hello
    if re.search(r"^(bonjour|salut|hello|bonsoir|coucou)", q):
        return (
            f"Bonjour {user.display_name if user else ''} ! Je suis TresorIA, votre assistant CFO. "
            f"Posez-moi une question sur votre trésorerie : "
            f"\"Solde T-Money\", \"Prévision 30 jours\", \"Anomalies\", \"Factures en retard\"."
        )

    # Fallback
    return (
        "Je n'ai pas compris votre question. Voici ce que je peux faire :\n"
        "• \"Combien ai-je en T-Money ?\" — solde par canal\n"
        "• \"Prévision 30 jours\" — trésorerie projetée\n"
        "• \"Combien d'anomalies ?\" — alertes en cours\n"
        "• \"Factures en retard\" — impayés à relancer\n"
        "• \"Top 5 clients\" — meilleurs payeurs"
    )
