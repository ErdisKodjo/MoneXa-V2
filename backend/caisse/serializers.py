"""
Serializers de l'API caisse (POS) — consommation par l'app mobile Flutter.

Contrat aligné sur l'app mobile :
- ProduitSerializer      : grille du terminal (prix_ttc en string décimale)
- SessionCaisseSerializer: session ouverte + rapport X (par_moyen aplati)
- VenteSerializer        : historique avec lignes + paiements imbriqués
- VenteCreateSerializer  : panier mobile {produit_id, quantite, remise_pct}
                           + paiements {moyen, montant, reference}
Les montants voyagent en string décimale (jamais de float, règle d'or n°1).
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from rest_framework import serializers

from .models import (
    LigneVente,
    MoyenPaiement,
    MouvementCaisse,
    PaiementVente,
    Produit,
    SessionCaisse,
    Vente,
)


class ProduitSerializer(serializers.ModelSerializer):
    categorie_nom = serializers.CharField(source="categorie.nom", read_only=True, default="")
    categorie_couleur = serializers.CharField(
        source="categorie.couleur", read_only=True, default="#063082"
    )
    stock_bas = serializers.BooleanField(read_only=True)

    class Meta:
        model = Produit
        fields = [
            "id", "reference", "ean", "designation", "categorie_nom",
            "categorie_couleur", "unite", "prix_ttc", "tva_taux",
            "stock", "stock_bas",
        ]


class MouvementCaisseSerializer(serializers.ModelSerializer):
    type_display = serializers.CharField(source="get_type_display", read_only=True)

    class Meta:
        model = MouvementCaisse
        fields = ["id", "type", "type_display", "montant", "note", "created_at"]


class LigneVenteSerializer(serializers.ModelSerializer):
    total_ht = serializers.SerializerMethodField()
    total_tva = serializers.SerializerMethodField()

    class Meta:
        model = LigneVente
        fields = [
            "id", "produit", "designation", "quantite",
            "prix_unitaire_ttc", "tva_taux", "remise_pct", "total_ttc",
            "total_ht", "total_tva",
        ]

    def get_total_ht(self, obj) -> str:
        return str(obj.total_ht)

    def get_total_tva(self, obj) -> str:
        return str(obj.total_tva)


class PaiementVenteSerializer(serializers.ModelSerializer):
    moyen_display = serializers.CharField(source="get_moyen_display", read_only=True)

    class Meta:
        model = PaiementVente
        fields = ["id", "moyen", "moyen_display", "montant", "reference"]


class VenteSerializer(serializers.ModelSerializer):
    lignes = LigneVenteSerializer(many=True, read_only=True)
    paiements = PaiementVenteSerializer(many=True, read_only=True)
    vendeur_nom = serializers.CharField(source="vendeur.display_name", read_only=True)
    statut_display = serializers.CharField(source="get_statut_display", read_only=True)

    class Meta:
        model = Vente
        fields = [
            "id", "reference", "session", "vendeur", "vendeur_nom",
            "client_name", "client_phone", "statut", "statut_display",
            "total_ht", "total_tva", "total_ttc", "remise_panier", "rendu",
            "lignes", "paiements", "created_at",
        ]


class SessionCaisseSerializer(serializers.ModelSerializer):
    vendeur_nom = serializers.CharField(source="vendeur.display_name", read_only=True)
    statut_display = serializers.CharField(source="get_statut_display", read_only=True)
    nb_ventes = serializers.SerializerMethodField()
    total_ventes = serializers.SerializerMethodField()

    class Meta:
        model = SessionCaisse
        fields = [
            "id", "vendeur", "vendeur_nom", "ouverte_at", "fermee_at",
            "fond_caisse", "statut", "statut_display",
            "comptage_physique", "ecart", "note", "nb_ventes", "total_ventes",
        ]

    def get_nb_ventes(self, obj) -> int:
        return obj.ventes.filter(statut="VALIDEE").count()

    def get_total_ventes(self, obj) -> str:
        from decimal import Decimal
        total = Decimal("0")
        for v in obj.ventes.filter(statut="VALIDEE"):
            total += v.total_ttc
        return str(total)


class OuvertureSerializer(serializers.Serializer):
    """POST /api/caisse/session/ — ouverture avec fond de caisse."""

    fond_caisse = serializers.CharField()

    def validate_fond_caisse(self, value: str) -> Decimal:
        try:
            amount = Decimal(value)
        except (InvalidOperation, TypeError):
            raise serializers.ValidationError("Fond de caisse invalide.")
        if amount < 0:
            raise serializers.ValidationError("Le fond de caisse ne peut pas être négatif.")
        return amount


class ClotureSerializer(serializers.Serializer):
    """POST /api/caisse/session/cloture/ — comptage physique + note."""

    comptage_physique = serializers.CharField()
    note = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_comptage_physique(self, value: str) -> Decimal:
        try:
            amount = Decimal(value)
        except (InvalidOperation, TypeError):
            raise serializers.ValidationError("Comptage physique invalide.")
        if amount < 0:
            raise serializers.ValidationError("Le comptage ne peut pas être négatif.")
        return amount


class LigneCreateSerializer(serializers.Serializer):
    """Ligne de panier mobile — le prix/TVA viennent du produit (snapshot serveur)."""

    produit_id = serializers.IntegerField()
    quantite = serializers.CharField(default="1")
    remise_pct = serializers.CharField(required=False, default="0")

    def validate_quantite(self, value: str) -> Decimal:
        try:
            q = Decimal(value)
        except (InvalidOperation, TypeError):
            raise serializers.ValidationError("Quantité invalide.")
        if q <= 0:
            raise serializers.ValidationError("La quantité doit être positive.")
        return q

    def validate_remise_pct(self, value: str) -> Decimal:
        try:
            r = Decimal(value or "0")
        except (InvalidOperation, TypeError):
            raise serializers.ValidationError("Remise invalide.")
        if r < 0 or r > 100:
            raise serializers.ValidationError("La remise doit être entre 0 et 100 %.")
        return r


class PaiementCreateSerializer(serializers.Serializer):
    moyen = serializers.ChoiceField(choices=MoyenPaiement.values)
    montant = serializers.CharField()
    reference = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_montant(self, value: str) -> Decimal:
        try:
            amount = Decimal(value)
        except (InvalidOperation, TypeError):
            raise serializers.ValidationError("Montant invalide.")
        if amount <= 0:
            raise serializers.ValidationError("Chaque paiement doit être strictement positif.")
        return amount


class VenteCreateSerializer(serializers.Serializer):
    """
    POST /api/caisse/ventes/ — vente idempotente (POS-10).

    La clé d'idempotence est facultative côté API (générée serveur si
    absente) mais l'app mobile DOIT l'envoyer pour garantir le replay
    offline sans doublon.
    """

    lignes = LigneCreateSerializer(many=True)
    paiements = PaiementCreateSerializer(many=True)
    remise_panier_pct = serializers.CharField(required=False, default="0")
    client_name = serializers.CharField(required=False, allow_blank=True, default="")
    client_phone = serializers.CharField(required=False, allow_blank=True, default="")
    idempotence_key = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_remise_panier_pct(self, value: str) -> Decimal:
        try:
            r = Decimal(value or "0")
        except (InvalidOperation, TypeError):
            raise serializers.ValidationError("Remise panier invalide.")
        if r < 0 or r > 100:
            raise serializers.ValidationError("La remise doit être entre 0 et 100 %.")
        return r

    def validate(self, attrs):
        if not attrs.get("lignes"):
            raise serializers.ValidationError({"lignes": "Le panier est vide."})
        if not attrs.get("paiements"):
            raise serializers.ValidationError({"paiements": "Aucun encaissement saisi."})
        key = (attrs.get("idempotence_key") or "").strip()
        if key:
            try:
                import uuid

                attrs["idempotence_key"] = str(uuid.UUID(key))
            except ValueError:
                raise serializers.ValidationError(
                    {"idempotence_key": "Clé d'idempotence : UUID attendu."}
                )
        return attrs
