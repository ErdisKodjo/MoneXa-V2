"""
URL configuration MoneXa — App web MVT (racine) + API REST + Django Admin + Swagger.
"""
from django.conf import settings
from django.conf.urls.i18n import i18n_patterns  # noqa: F401
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
    TokenVerifyView,
)
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)

from accounts.viewsets import MeViewSet, UserViewSet
from accounts.views import Toggle2FAView
from finance.viewsets import (
    AccountViewSet,
    InvoiceViewSet,
    PaymentViewSet,
    ExpenseViewSet,
)
from finance.webhook import GatewayWebhookView
from reporting.views import (
    DashboardSummaryView,
    ForecastView,
    AnomaliesView,
    AuditLogListView,
    ExportView,
)
from assistant.views import AskView

router = DefaultRouter()
router.register(r"users", UserViewSet, basename="user")
router.register(r"accounts", AccountViewSet, basename="account")
router.register(r"invoices", InvoiceViewSet, basename="invoice")
router.register(r"payments", PaymentViewSet, basename="payment")
router.register(r"expenses", ExpenseViewSet, basename="expense")

urlpatterns = [
    # ── Racine → Application web MVT (fonctionnelle, non démo) ──────────
    path("", RedirectView.as_view(url="/dashboard/", permanent=False)),

    # Admin
    path("admin/", admin.site.urls),

    # ── Couche MVT web (sessions, templates, forms) ────────────────────
    path("", include("webui.urls")),

    # i18n — changement de langue (FR / Ewé / Kabyé)
    path("i18n/", include("django.conf.urls.i18n")),

    # Auth
    path("api/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/auth/verify/", TokenVerifyView.as_view(), name="token_verify"),
    path("api/auth/me/", MeViewSet.as_view({"get": "retrieve"}), name="auth_me"),
    path("api/auth/me/2fa/", Toggle2FAView.as_view(), name="auth_me_2fa"),

    # API REST
    path("api/", include(router.urls)),

    # Reporting & dashboard
    path("api/dashboard/summary/", DashboardSummaryView.as_view(), name="dashboard_summary"),
    path("api/reports/forecast/", ForecastView.as_view(), name="reports_forecast"),
    path("api/reports/export/", ExportView.as_view(), name="reports_export"),
    path("api/anomalies/", AnomaliesView.as_view(), name="anomalies_list"),
    path("api/audit-logs/", AuditLogListView.as_view(), name="audit_logs_list"),

    # Assistant TresorIA
    path("api/assistant/ask/", AskView.as_view(), name="assistant_ask"),

    # Passerelles Mobile Money — webhook opérateurs (signature HMAC)
    path(
        "api/gateways/webhook/<str:operator>/",
        GatewayWebhookView.as_view(),
        name="gateway_webhook",
    ),

    # Documentation API
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/schema/swagger-ui/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger_ui",
    ),
    path(
        "api/schema/redoc/",
        SpectacularRedocView.as_view(url_name="schema"),
        name="redoc",
    ),
]

# Fichiers média (preuves de paiement) en développement
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
