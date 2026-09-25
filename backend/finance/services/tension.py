"""
Alerte de tension de trésorerie (v2.3 — « ANTICIPER », feature jury).

Le document stratégie (« jury ») l'exige pour le WOW #4 :
    « Risque de tension de trésorerie dans 18 jours »
    « Cause probable : sortie importante prévue + baisse habituelle
      des encaissements. »

Principe :
- Balance projetée jour par jour = solde actuel + flux nets prévus
  (Holt-Winters pré-calculés dans ForecastCache par generate_forecast /
  seed_demo — recalcul à la volée uniquement si le cache manque).
- Deux scénarios : médian (forecast) et pessimiste (borne basse 80 %).
- Plancher = 15 % du solde actuel (configurable via TENSION_FLOOR_RATIO)
  — alerte déclenchée au premier jour sous le plancher.
- Cause probable = jour de pire flux négatif autour de la tension.

Aucun SQL brut, aucun LLM — 100 % déterministe et instantané.
"""
from __future__ import annotations

from datetime import date, timedelta

from django.utils import timezone

from finance.models import ForecastCache

HORIZON = 30
FLOOR_RATIO = 0.15  # alerte si balance projetée < 15 % du solde actuel


def _setting_float(name: str, default: float) -> float:
    try:
        from django.conf import settings
        return float(getattr(settings, name, default))
    except Exception:
        return default


def _daily_forecast(days: int = HORIZON) -> dict:
    """Flux nets prévus par jour — cache d'abord, Holt-Winters en secours."""
    try:
        cached = ForecastCache.objects.get(days=days)
        forecast = [float(x) for x in cached.forecast_data]
        low = [float(x) for x in (cached.confidence_low or forecast)]
        if len(forecast) >= days:
            return {"forecast": forecast[:days], "low": low[:days]}
    except ForecastCache.DoesNotExist:
        pass

    from finance.services.forecast import forecast_cashflow

    result = forecast_cashflow(days=days)
    return {
        "forecast": [float(x) for x in result["forecast"][:days]],
        "low": [float(x) for x in result["confidence_low"][:days]],
    }


def _cause_probable(forecast: list[float], start_idx: int, window: int = 5) -> str:
    """Cause la plus vraisemblable : le pire flux négatif proche de la tension."""
    window_start = max(0, start_idx - 2)
    window_end = min(len(forecast), start_idx + window)
    slice_ = forecast[window_start:window_end]
    if not slice_:
        return "baisse inhabituelle des encaissements"
    worst = min(slice_)
    worst_day = window_start + slice_.index(worst)
    if worst >= 0:
        return "encaissements projetés en baisse par rapport à l'historique"
    detail = (
        f"sortie nette prévue d'environ {abs(worst):,.0f} FCFA "
        f"dans {worst_day + 1} jour(s)"
    ).replace(",", " ")
    return f"{detail} + tendance des encaissements en baisse"


def tension_alert(horizon: int = HORIZON) -> dict | None:
    """
    Détecte le premier jour où la trésorerie projetée passe sous le plancher.

    Retourne None si la trésorerie reste saine sur l'horizon, sinon :
    {
        "days_away": int,           # jours avant la tension
        "date": date,               # jour de bascule
        "balance_median": float,    # balance projetée (scénario médian)
        "balance_pessimist": float, # balance projetée (borne basse 80 %)
        "floor": float,             # plancher utilisé
        "severity": "ÉLEVÉE"|"MODÉRÉE",
        "cause": str,               # cause probable
        "horizon": int,
    }
    """
    solde_total = _current_balance()
    if solde_total <= 0:
        # Base vide ou solde négatif : pas de projection significative
        return None

    daily = _daily_forecast(horizon)
    forecast, low = daily["forecast"], daily["low"]
    if not forecast:
        return None

    floor = _setting_float("TENSION_FLOOR_RATIO", FLOOR_RATIO) * solde_total
    today = timezone.localdate()

    cum_median = 0.0
    cum_pess = 0.0
    for i, (median, pess) in enumerate(zip(forecast, low)):
        cum_median += median
        cum_pess += pess
        balance_median = solde_total + cum_median
        balance_pess = solde_total + cum_pess
        if balance_pess < floor or balance_median < floor:
            under_zero = balance_pess < 0
            return {
                "days_away": i + 1,
                "date": today + timedelta(days=i + 1),
                "balance_median": round(balance_median, 2),
                "balance_pessimist": round(balance_pess, 2),
                "floor": round(floor, 2),
                "severity": "ÉLEVÉE" if under_zero or balance_median < 0 else "MODÉRÉE",
                "cause": _cause_probable(forecast, i),
                "horizon": horizon,
            }
    return None


def _current_balance() -> float:
    """Solde total consolidé (même convention que compute_kpis)."""
    from django.db.models import Sum

    from finance.models import Payment

    total = Payment.objects.aggregate(t=Sum("amount"))["t"]
    return float(total) if total else 0.0
