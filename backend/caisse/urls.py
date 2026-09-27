"""
URLs du module caisse (POS) — inclus à la racine sous préfixe caisse/.

Noms préfixés caisse_ pour éviter toute collision avec la WebUI existante.
"""
from django.urls import path

from . import views

urlpatterns = [
    # Terminal de vente (POS)
    path("caisse/", views.POSTerminalView.as_view(), name="caisse_pos"),
    # Session de caisse : ouverture, rapport X, mouvements, clôture Z
    path("caisse/session/", views.CaisseSessionView.as_view(), name="caisse_session"),
    # Ventes
    path("caisse/ventes/", views.CaisseVentesListView.as_view(), name="caisse_ventes"),
    path(
        "caisse/ventes/<str:reference>/annuler/",
        views.CaisseVenteAnnulerView.as_view(),
        name="caisse_vente_annuler",
    ),
    # Tickets (POS-05)
    path(
        "caisse/ventes/<str:reference>/ticket.pdf",
        views.CaisseTicketPDFView.as_view(),
        name="caisse_ticket_pdf",
    ),
    path(
        "caisse/ventes/<str:reference>/ticket.escpos",
        views.CaisseTicketESCPOSView.as_view(),
        name="caisse_ticket_escpos",
    ),
    path(
        "caisse/ventes/<str:reference>/ticket.txt",
        views.CaisseTicketTextView.as_view(),
        name="caisse_ticket_txt",
    ),
    # Catalogue (POS-01)
    path("caisse/catalogue/", views.CaisseCatalogueView.as_view(), name="caisse_catalogue"),
    path(
        "caisse/catalogue/import/",
        views.CaisseCatalogueImportView.as_view(),
        name="caisse_catalogue_import",
    ),
    path(
        "caisse/catalogue/export.csv",
        views.CaisseCatalogueExportView.as_view(),
        name="caisse_catalogue_export",
    ),
]
