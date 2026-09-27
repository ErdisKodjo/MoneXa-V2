"""
MoneXa — Module Système de caisse (POS), cahier des charges entreprise v3.0 §5.

Conception conforme aux exigences POS-01 → POS-09 (Must) de la phase 1 :

RÈGLES D'OR (héritées de finance) :
1. Pas de FloatField pour l'argent → DecimalField (14, 2) max.
2. Idempotence offline : Vente.idempotence_key UUID unique au niveau DB —
   un rejou réseau/offline ne peut pas créer de doublon (POS-10).
3. Toute écriture métier dans transaction.atomic() — vente atomique :
   lignes + paiements + stock + trésorerie + session (POS-08).
4. Snapshots : la ligne de vente fige désignation/prix/TVA au moment
   de la vente (le catalogue peut changer ensuite sans fausser l'historique).

Intégration plateforme (§5.5) :
- Chaque PaiementVente crée un finance.Payment natif (provider_ref « POS-… »,
  statut RECONCILIE, match_method MANUEL) → journal de caisse, KPIs et
  exports PDF reflètent l'activité du point de vente sans double saisie.
- Chaque vente décrémente le stock Produit.stock ; sous le seuil d'alerte
  → Notification aux gérants (réapprovisionnement).
- Écart de caisse au-delà du seuil de tolérance à la clôture Z →
  Notification (kind ANOMALIE) aux gérants + AuditLog immuable (POS-07).
"""
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


# ──────────────────────────────────────────────────────────────────────────
# Choices
# ──────────────────────────────────────────────────────────────────────────
class MoyenPaiement(models.TextChoices):
    """Moyens d'encaissement au comptoir (POS-04 — multi-paiement)."""

    ESPECES = "ESPECES", "Espèces"
    TMONEY = "TMONEY", "T-Money"
    MOOV = "MOOV", "Moov Money"
    FLOOZ = "FLOOZ", "Flooz"
    CARTE = "CARTE", "Carte bancaire (terminal externe)"


class VenteStatut(models.TextChoices):
    VALIDEE = "VALIDEE", "Validée"
    ANNULEE = "ANNULEE", "Annulée"


class SessionStatut(models.TextChoices):
    OUVERTE = "OUVERTE", "Ouverte"
    FERMEE = "FERMEE", "Fermée"


class MouvementType(models.TextChoices):
    """Mouvements d'espèces physiques dans la session (POS-06)."""

    VENTE_ESPECES = "VENTE_ESPECES", "Vente en espèces"
    DEPOT = "DEPOT", "Dépôt de sécurisation"
    RETRAIT = "RETRAIT", "Retrait (fonds)"
    DEPENSE = "DEPENSE", "Dépense au comptant"
    ECART = "ECART", "Écart de clôture"


# ──────────────────────────────────────────────────────────────────────────
# Catalogue produits (POS-01)
# ──────────────────────────────────────────────────────────────────────────
class Categorie(models.Model):
    """Catégorie de produits — présentée en chips colorées sur le POS."""

    nom = models.CharField(max_length=80, unique=True, verbose_name="Nom")
    couleur = models.CharField(
        max_length=7, default="#063082", verbose_name="Couleur (hex)",
        help_text="Couleur d'accent dans l'interface de vente.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Catégorie de produit"
        verbose_name_plural = "Catégories de produits"
        ordering = ["nom"]

    def __str__(self) -> str:
        return self.nom


class Produit(models.Model):
    """
    Article du catalogue : référence interne, EAN-13 scannable (POS-03),
    prix de vente TTC, TVA togolaise standard 18 %, coût d'achat optionnel
    pour la marge, stock suivi + seuil d'alerte (POS-09).
    """

    reference = models.CharField(
        max_length=30, unique=True, db_index=True, blank=True, verbose_name="Référence",
        help_text="Auto-générée (ART-000001) si laissée vide.",
    )
    ean = models.CharField(
        max_length=13, blank=True, default="", db_index=True,
        verbose_name="Code-barres EAN-13",
        help_text="13 chiffres ; scannable caméra mobile ou lecteur USB (POS-03).",
    )
    designation = models.CharField(max_length=200, verbose_name="Désignation")
    categorie = models.ForeignKey(
        Categorie, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="produits", verbose_name="Catégorie",
    )
    unite = models.CharField(max_length=20, default="pièce", verbose_name="Unité de vente")
    prix_ttc = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0"))],
        verbose_name="Prix de vente TTC (FCFA)",
    )
    tva_taux = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("18.00"),
        validators=[MinValueValidator(Decimal("0"))],
        verbose_name="Taux de TVA (%)",
    )
    cout_achat = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        verbose_name="Coût d'achat (optionnel)",
    )
    stock = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0"), verbose_name="Stock",
    )
    seuil_alerte = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0"),
        verbose_name="Seuil d'alerte stock",
    )
    image = models.ImageField(
        upload_to="produits/%Y/%m/", blank=True, null=True, verbose_name="Image",
    )
    actif = models.BooleanField(default=True, verbose_name="Actif")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Produit"
        verbose_name_plural = "Catalogue produits"
        ordering = ["designation"]

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = self.generate_reference()
        super().save(*args, **kwargs)

    def clean(self):
        # Référence auto-générée au nettoyage (formulaire peut l'omettre)
        if not self.reference:
            self.reference = self.generate_reference()
        if self.ean and not (self.ean.isdigit() and len(self.ean) == 13):
            raise ValidationError({"ean": "L'EAN doit comporter exactement 13 chiffres."})

    def __str__(self) -> str:
        return f"{self.reference} — {self.designation}"

    @classmethod
    def generate_reference(cls) -> str:
        """Référence interne auto : ART-000001."""
        last = cls.objects.order_by("-id").first()
        seq = (last.id + 1) if last else 1
        while cls.objects.filter(reference=f"ART-{seq:06d}").exists():
            seq += 1
        return f"ART-{seq:06d}"

    @property
    def stock_bas(self) -> bool:
        """True si le stock est sous (ou égal à) son seuil d'alerte."""
        return self.stock <= self.seuil_alerte


# ──────────────────────────────────────────────────────────────────────────
# Sessions de caisse (POS-06 / POS-07)
# ──────────────────────────────────────────────────────────────────────────
class SessionCaisse(models.Model):
    """
    Session de caisse d'un vendeur : fond de caisse déclaré à l'ouverture,
    mouvements d'espèces, rapport intermédiaire X, clôture définitive Z
    avec comptage physique et écart.
    """

    vendeur = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="sessions_caisse", verbose_name="Vendeur",
    )
    ouverte_at = models.DateTimeField(auto_now_add=True, verbose_name="Ouverte le")
    fermee_at = models.DateTimeField(null=True, blank=True, verbose_name="Fermée le")
    fond_caisse = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0"), verbose_name="Fond de caisse",
    )
    statut = models.CharField(
        max_length=10, choices=SessionStatut.choices, default=SessionStatut.OUVERTE,
        db_index=True, verbose_name="Statut",
    )
    comptage_physique = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        verbose_name="Comptage physique (espèces)",
    )
    ecart = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        verbose_name="Écart (physique − théorique)",
    )
    note = models.TextField(blank=True, default="", verbose_name="Note de clôture")

    class Meta:
        verbose_name = "Session de caisse"
        verbose_name_plural = "Sessions de caisse"
        ordering = ["-ouverte_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["vendeur"],
                condition=models.Q(statut="OUVERTE"),
                name="unique_session_ouverte_par_vendeur",
            ),
        ]
        indexes = [models.Index(fields=["statut", "ouverte_at"])]

    def __str__(self) -> str:
        return f"Session #{self.pk} — {self.vendeur.display_name} ({self.get_statut_display()})"


class MouvementCaisse(models.Model):
    """Mouvement d'espèces physiques (vente, dépôt, retrait, dépense, écart)."""

    session = models.ForeignKey(
        SessionCaisse, on_delete=models.PROTECT, related_name="mouvements",
        verbose_name="Session",
    )
    type = models.CharField(max_length=20, choices=MouvementType.choices, verbose_name="Type")
    montant = models.DecimalField(
        max_digits=12, decimal_places=2, verbose_name="Montant (FCFA)",
        help_text="Positif = entrée d'espèces, négatif = sortie.",
    )
    vente = models.ForeignKey(
        "caisse.Vente", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="mouvements", verbose_name="Vente liée",
    )
    note = models.CharField(max_length=200, blank=True, default="", verbose_name="Note")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="mouvements_caisse",
        null=True, blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Mouvement de caisse"
        verbose_name_plural = "Mouvements de caisse"
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.get_type_display()} {self.montant:+,.2f} FCFA"


# ──────────────────────────────────────────────────────────────────────────
# Ventes (POS-02 / POS-04 / POS-05)
# ──────────────────────────────────────────────────────────────────────────
class Vente(models.Model):
    """
    Vente au comptoir : panier figé, multi-paiement (espèces avec rendu,
    mobile money, carte déclarative), référence VTE-YYYY-XXXX et clé
    d'idempotence UUID pour le replay offline (POS-10).
    """

    reference = models.CharField(max_length=20, unique=True, db_index=True, verbose_name="Référence")
    idempotence_key = models.UUIDField(
        unique=True, db_index=True, verbose_name="Clé d'idempotence",
        help_text="Identifiant unique de vente généré par le client POS ; "
                  "garantit qu'un replay réseau ne crée pas de doublon.",
    )
    session = models.ForeignKey(
        SessionCaisse, on_delete=models.PROTECT, related_name="ventes", verbose_name="Session",
    )
    vendeur = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ventes",
        verbose_name="Vendeur",
    )
    client_name = models.CharField(
        max_length=200, blank=True, default="", verbose_name="Client (facultatif)",
        help_text="Vide = client anonyme. Un client enregistré permet le suivi de fiabilité.",
    )
    client_phone = models.CharField(max_length=20, blank=True, default="", verbose_name="Téléphone client")
    statut = models.CharField(
        max_length=10, choices=VenteStatut.choices, default=VenteStatut.VALIDEE,
        db_index=True, verbose_name="Statut",
    )
    total_ht = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    total_tva = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    total_ttc = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    remise_panier = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0"), verbose_name="Remise panier",
    )
    rendu = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0"), verbose_name="Monnaie rendue",
    )
    ticket_imprime = models.BooleanField(
        default=False, verbose_name="Ticket imprimé",
        help_text="False = ticket en file d'impression (mode dégradé sans imprimante).",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Vente POS"
        verbose_name_plural = "Ventes POS"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["statut", "created_at"])]

    def __str__(self) -> str:
        return f"{self.reference} — {self.total_ttc:,.2f} FCFA ({self.get_statut_display()})"

    @classmethod
    def generate_reference(cls) -> str:
        """Référence auto : VTE-YYYY-XXXX (séquence par année)."""
        year = timezone.now().year
        prefix = f"VTE-{year}-"
        last = cls.objects.filter(reference__startswith=prefix).order_by("-reference").first()
        if last:
            try:
                seq = int(last.reference.split("-")[-1]) + 1
            except ValueError:
                seq = 1
        else:
            seq = 1
        return f"{prefix}{seq:04d}"


class LigneVente(models.Model):
    """Ligne de panier — snapshot désignation/prix/TVA au moment de la vente."""

    vente = models.ForeignKey(Vente, on_delete=models.CASCADE, related_name="lignes")
    produit = models.ForeignKey(
        Produit, on_delete=models.SET_NULL, null=True, blank=True, related_name="lignes",
        verbose_name="Produit",
    )
    designation = models.CharField(max_length=200, verbose_name="Désignation (figée)")
    quantite = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("1"),
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    prix_unitaire_ttc = models.DecimalField(max_digits=12, decimal_places=2)
    tva_taux = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("18.00"))
    remise_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0"), verbose_name="Remise ligne (%)",
    )
    total_ttc = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="Total ligne TTC")

    class Meta:
        verbose_name = "Ligne de vente"
        verbose_name_plural = "Lignes de vente"
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.designation} ×{self.quantite} = {self.total_ttc:,.2f}"

    @property
    def total_ht(self) -> Decimal:
        """Part HT de la ligne après remise (TVA extraite au prorata)."""
        return (self.total_ttc / (Decimal("1") + self.tva_taux / Decimal("100"))).quantize(Decimal("0.01"))

    @property
    def total_tva(self) -> Decimal:
        return (self.total_ttc - self.total_ht).quantize(Decimal("0.01"))


class PaiementVente(models.Model):
    """
    Encaissement d'une vente — une vente peut combiner plusieurs moyens
    (ex. espèces + T-Money). Chaque ligne crée le mouvement natif de
    trésorerie correspondant (POS-08).
    """

    vente = models.ForeignKey(Vente, on_delete=models.PROTECT, related_name="paiements")
    moyen = models.CharField(max_length=10, choices=MoyenPaiement.choices, verbose_name="Moyen")
    montant = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Montant")
    reference = models.CharField(
        max_length=60, blank=True, default="",
        verbose_name="N° de transaction (repli manuel)",
        help_text="Référence opérateur saisie manuellement si la passerelle est indisponible.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Paiement de vente"
        verbose_name_plural = "Paiements de vente"
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.get_moyen_display()} {self.montant:,.2f} FCFA — {self.vente.reference}"
