"""
WebUI — couche Django MVT fonctionnelle (vues render + templates + forms).

Conforme au cahier des charges « Django MVT fonctionnel et non démo » :
- Model   : réutilise finance/accounts/auditing/reporting sans duplication
- View    : vues basées classes + mixins RBAC, rendu serveur (render)
- Template: design system MoneXa (docs/design-system.md)

Aucune logique métier nouvelle ici : on appelle les services existants
(matcher, ai_pipeline, anomalies, forecast, compute_kpis, answer_question).
"""
from django.apps import AppConfig


class WebuiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "webui"
    verbose_name = "Interface web MoneXa"
