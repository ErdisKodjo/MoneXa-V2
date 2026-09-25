"""
URLs WebUI — couche MVT à la racine (avant l'API).

Routes :
- /login/  /logout/                       — sessions Django (CSRF)
- /dashboard/                             — KPIs (connecté)
- /factures/  /factures/nouvelle/          — factures
- /paiements/ (+ preuve, sms, decision)   — réconciliation
- /depenses/  /depenses/nouvelle/          — dépenses
- /anomalies/  /audit/                    — Gérant
- /assistant/                             — TresorIA
- /exports/ (+ CSV)                       — Comptable+
"""
from django.urls import path

from . import views

urlpatterns = [
    # Auth
    path("login/", views.WebLoginView.as_view(), name="login"),
    path("logout/", views.WebLogoutView.as_view(), name="logout"),
    # Dashboard
    path("dashboard/", views.DashboardView.as_view(), name="dashboard"),
    # Factures
    path("factures/", views.InvoiceListView.as_view(), name="invoices"),
    path("factures/nouvelle/", views.InvoiceCreateView.as_view(), name="invoice_create"),
    # Paiements
    path("paiements/", views.PaymentListView.as_view(), name="payments"),
    path(
        "paiements/preuve/",
        views.PaymentEvidenceUploadView.as_view(),
        name="payment_evidence",
    ),
    path("paiements/sms/", views.PaymentSmsView.as_view(), name="payment_sms"),
    path(
        "paiements/<int:pk>/decision/",
        views.PaymentDecisionView.as_view(),
        name="payment_decision",
    ),
    # Dépenses
    path("depenses/", views.ExpenseListView.as_view(), name="expenses"),
    path("depenses/nouvelle/", views.ExpenseCreateView.as_view(), name="expense_create"),
    # Gérant
    path("anomalies/", views.AnomaliesView.as_view(), name="anomalies"),
    path("audit/", views.AuditLogView.as_view(), name="audit"),
    # TresorIA
    path("assistant/", views.AssistantView.as_view(), name="assistant"),
    # Exports
    path("exports/", views.ExportsView.as_view(), name="exports"),
    path("exports/paiements.csv", views.PaymentExportView.as_view(), name="export_payments"),
    path("exports/depenses.csv", views.ExpenseExportView.as_view(), name="export_expenses"),
]
