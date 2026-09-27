"""Admin Django du module caisse — gestion back-office standard."""
from django.contrib import admin

from .models import (
    Categorie,
    LigneVente,
    MouvementCaisse,
    PaiementVente,
    Produit,
    SessionCaisse,
    Vente,
)


@admin.register(Categorie)
class CategorieAdmin(admin.ModelAdmin):
    list_display = ("nom", "couleur")
    search_fields = ["nom"]


@admin.register(Produit)
class ProduitAdmin(admin.ModelAdmin):
    list_display = ("reference", "designation", "categorie", "prix_ttc", "stock", "seuil_alerte", "actif")
    list_filter = ("actif", "categorie")
    search_fields = ["reference", "ean", "designation"]
    readonly_fields = ("reference",)


class LigneVenteInline(admin.TabularInline):
    model = LigneVente
    extra = 0
    readonly_fields = ("designation", "quantite", "prix_unitaire_ttc", "tva_taux", "remise_pct", "total_ttc")


class PaiementVenteInline(admin.TabularInline):
    model = PaiementVente
    extra = 0
    readonly_fields = ("moyen", "montant", "reference")


@admin.register(Vente)
class VenteAdmin(admin.ModelAdmin):
    list_display = ("reference", "created_at", "vendeur", "total_ttc", "statut")
    list_filter = ("statut",)
    search_fields = ["reference", "client_name"]
    inlines = [LigneVenteInline, PaiementVenteInline]


@admin.register(SessionCaisse)
class SessionCaisseAdmin(admin.ModelAdmin):
    list_display = ("pk", "vendeur", "ouverte_at", "fermee_at", "statut", "ecart")
    list_filter = ("statut",)
    search_fields = ["vendeur__email"]


@admin.register(MouvementCaisse)
class MouvementCaisseAdmin(admin.ModelAdmin):
    list_display = ("type", "montant", "session", "created_at")
    list_filter = ("type",)
