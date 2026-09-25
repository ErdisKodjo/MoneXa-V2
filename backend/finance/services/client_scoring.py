"""
Scoring de fiabilité clients (v2.3 — feature Tier 2 du README).

Pour chaque client (factures + paiements rapprochés), calcule un score
0–100 déterministe et explicable à partir de 4 signaux :

  1. Taux de règlement        — factures payées / factures émises
  2. Retards en cours         — factures EN_ATTENTE dépassant l'échéance
  3. Ponctualité moyenne      — délai moyen de paiement vs échéance
  4. Anomalies de paiement    — paiements ANOMALIE / paiements du client

Aucun SQL brut : uniquement l'ORM Django. Aucun état mutable — le score
se recalcule à la demande (dashboard, API).
"""
from __future__ import annotations

from django.db.models import Count, Q
from django.utils import timezone

from finance.models import Invoice, Payment

# Barèmes (points retirés au score de départ 100)
PENALITE_NON_REGLE = 40      # x (1 - taux_règlement)
PENALITE_RETARD = 25         # x (part de factures en retard)
PENALITE_PONCTUALITE = 2     # x (jours de retard moyen, plafonné à 15 pts)
PENALITE_ANOMALIE = 15       # x (part de paiements en anomalie)
PLAFOND_PONCTUALITE = 15.0

# Segments affichés dans l'UI
SEUIL_FIABLE = 80
SEUIL_VIGILANCE = 50

LABELS = {"FIABLE": "Fiable", "VIGILANCE": "Vigilance", "RISQUE": "Risque"}


def _label(score: float) -> str:
    if score >= SEUIL_FIABLE:
        return LABELS["FIABLE"]
    if score >= SEUIL_VIGILANCE:
        return LABELS["VIGILANCE"]
    return LABELS["RISQUE"]


def _tone(score: float) -> str:
    """Classe CSS cohérente avec les badges du webui."""
    if score >= SEUIL_FIABLE:
        return "success"
    if score >= SEUIL_VIGILANCE:
        return "warning"
    return "danger"


def client_reliability_scores() -> list[dict]:
    """
    Score de fiabilité par client, trié du moins fiable au plus fiable
    (le Gérant regarde d'abord les clients à risque).

    Retourne une liste de dicts :
    {name, invoices, paid, on_time, late_open, avg_delay_days, anomalies,
     outstanding, score, label, tone}
    """
    today = timezone.localdate()

    invoices = list(
        Invoice.objects.exclude(status="ANNULE").values(
            "client_name", "status", "issue_date", "due_date", "amount"
        )
    )
    payments = list(
        Payment.objects.exclude(status="NON_RATTACHE").values(
            "payer_name", "invoice__client_name", "status", "paid_at", "amount"
        )
    )

    if not invoices and not payments:
        return []

    # ── Agrégation factures par client ──────────────────────────────────
    clients: dict[str, dict] = {}

    def _bucket(name: str) -> dict:
        return clients.setdefault(
            name,
            {
                "invoices": 0, "paid": 0, "on_time": 0, "late_open": 0,
                "delay_total": 0.0, "delay_count": 0, "anomalies": 0,
                "payments": 0, "outstanding": 0.0, "billed": 0.0, "collected": 0.0,
            },
        )

    for inv in invoices:
        name = (inv["client_name"] or "—").strip() or "—"
        b = _bucket(name)
        b["invoices"] += 1
        b["billed"] += float(inv["amount"])
        if inv["status"] == "RECONCILIE":
            b["paid"] += 1
        elif inv["status"] == "EN_ATTENTE" and inv["due_date"] and inv["due_date"] < today:
            b["late_open"] += 1
            b["outstanding"] += float(inv["amount"])

    # Ponctualité : date du 1er paiement rattaché vs échéance de la facture
    paid_dates: dict[str, list] = {}
    for p in payments:
        name = (p["invoice__client_name"] or p["payer_name"] or "—").strip() or "—"
        b = _bucket(name)
        b["payments"] += 1
        if p["status"] == "ANOMALIE":
            b["anomalies"] += 1
        if p["invoice__client_name"]:
            b["collected"] += float(p["amount"])
            paid_dates.setdefault(name, []).append(
                (timezone.localdate(p["paid_at"]), p["status"])
            )

    for inv in Invoice.objects.exclude(status="ANNULE").only(
        "client_name", "due_date"
    ):
        name = (inv.client_name or "—").strip() or "—"
        dates = paid_dates.get(name)
        if dates and inv.due_date:
            paid_on, _st = dates[0]
            b = _bucket(name)
            b["on_time"] += 1 if paid_on <= inv.due_date else 0
            delay = (paid_on - inv.due_date).days
            if delay > 0:
                b["delay_total"] += delay
                b["delay_count"] += 1

    # ── Score par client ────────────────────────────────────────────────
    out = []
    for name, b in clients.items():
        invoices_n = b["invoices"] or 0
        paid_n = b["paid"] or 0
        payments_n = b["payments"] or 0

        regle_ratio = (paid_n / invoices_n) if invoices_n else 1.0
        retard_ratio = (b["late_open"] / invoices_n) if invoices_n else 0.0
        anomalie_ratio = (b["anomalies"] / payments_n) if payments_n else 0.0
        avg_delay = (b["delay_total"] / b["delay_count"]) if b["delay_count"] else 0.0

        score = 100.0
        score -= PENALITE_NON_REGLE * (1.0 - regle_ratio)
        score -= PENALITE_RETARD * retard_ratio
        score -= min(PLAFOND_PONCTUALITE, PENALITE_PONCTUALITE * avg_delay)
        score -= PENALITE_ANOMALIE * anomalie_ratio
        score = max(0.0, min(100.0, round(score)))

        out.append(
            {
                "name": name,
                "invoices": invoices_n,
                "paid": paid_n,
                "on_time": b["on_time"],
                "late_open": b["late_open"],
                "avg_delay_days": round(avg_delay, 1),
                "anomalies": b["anomalies"],
                "outstanding": round(b["outstanding"], 2),
                "billed": round(b["billed"], 2),
                "collected": round(b["collected"], 2),
                "score": score,
                "label": _label(score),
                "tone": _tone(score),
            }
        )

    out.sort(key=lambda c: (c["score"], -c["outstanding"]))
    return out


def risky_clients(limit: int = 3) -> list[dict]:
    """Top N clients à surveiller (score < 80), pour le dashboard TresorIA."""
    return [c for c in client_reliability_scores() if c["score"] < SEUIL_FIABLE][:limit]
