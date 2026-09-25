"""
Mixins RBAC pour les vues MVT — réutilisent les helpers du modèle User.

Hiérarchie : GERANT > COMPTABLE > CAISSIER
- Caissier    : saisie (factures, paiements, dépenses) — ses propres objets
- Comptable   : validation, dashboard complet, exports
- Gérant      : anomalies, audit, tout
"""
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin


class CaissierRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Tout utilisateur authentifié (Caissier minimum)."""

    def test_func(self) -> bool:
        u = self.request.user
        return u.is_authenticated and u.is_caissier_or_higher()


class ComptableRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Comptable ou Gérant uniquement."""

    def test_func(self) -> bool:
        u = self.request.user
        return u.is_authenticated and u.is_comptable_or_higher()


class GerantRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Gérant uniquement."""

    def test_func(self) -> bool:
        u = self.request.user
        return u.is_authenticated and u.is_gerant()
