"""
MoneXa finance models.

RÈGLES D'OR FINANCIÈRES (cahier des charges §6.1) :
1. Pas de FloatField pour l'argent → DecimalField(14, 2)
2. Contrainte DB unique=True sur provider_ref (anti-doublon natif)
3. Toute écriture dans transaction.atomic()
"""
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import models
from django.conf import settings


# ──────────────────────────────────────────────────────────────────────────
# Choices
# ──────────────────────────────────────────────────────────────────────────
class Channel(models.TextChoices):
    TMONEY = "TMONEY", "T-Money"
    MOOV = "MOOV", "Moov Money"
    FLOOZ = "FLOOZ", "Flooz"
    BANQUE = "BANQUE", "Banque"
    ESPECES = "ESPECES", "Espèces"


class InvoiceStatus(models.TextChoices):
    EN_ATTENTE = "EN_ATTENTE", "En attente"
    RECONCILIE = "RECONCILIE", "Réconcilié"
    ANOMALIE = "ANOMALIE", "Anomalie"
    ANNULE = "ANNULE", "Annulé"


class PaymentStatus(models.TextChoices):
    NON_RATTACHE = "NON_RATTACHE", "Non rattaché"
    A_VALIDER = "A_VALIDER", "À valider"
    RECONCILIE = "RECONCILIE", "Réconcilié"
    ANOMALIE = "ANOMALIE", "Anomalie"


class MatchMethod(models.TextChoices):
    AUTO_REF = "AUTO_REF", "Référence exacte"
    AUTO_MONTANT = "AUTO_MONTANT", "Montant + 7 jours"
    FUZZY = "FUZZY", "Fuzzy nom/téléphone"
    MANUEL = "MANUEL", "Validation manuelle"
    IA = "IA", "IA"


class ExpenseCategory(models.TextChoices):
    LOYER = "LOYER", "Loyer"
    SALAIRES = "SALAIRES", "Salaires"
    FOURNISSEURS = "FOURNISSEURS", "Fournisseurs"
    TRANSPORT = "TRANSPORT", "Transport"
    FOURNITURES = "FOURNITURES", "Fournitures"
    AUTRE = "AUTRE", "Autre"


# ──────────────────────────────────────────────────────────────────────────
# Models
# ──────────────────────────────────────────────────────────────────────────
class Account(models.Model):
    """Treasury account per channel (T-Money, Moov, Flooz, Banque, Espèces)."""
    name = models.CharField(max_length=100, verbose_name="Nom")
    channel = models.CharField(
        max_length=20, choices=Channel.choices, db_index=True, verbose_name="Canal"
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="accounts",
        verbose_name="Propriétaire",
    )
    is_active = models.BooleanField(default=True, verbose_name="Actif")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Compte de trésorerie"
        verbose_name_plural = "Comptes de trésorerie"
        unique_together = [("name", "channel")]

    def __str__(self) -> str:
        return f"{self.name} ({self.get_channel_display()})"


class Invoice(models.Model):
    """
    Invoice émise par la PME — référence auto-générée FACT-YYYY-XXXX.
    """
    reference = models.CharField(max_length=20, unique=True, db_index=True)
    client_name = models.CharField(max_length=200, verbose_name="Client")
    client_phone = models.CharField(max_length=20, blank=True, default="")
    amount = models.DecimalField(
        max_digits=14, decimal_places=2, verbose_name="Montant (FCFA)"
    )
    issue_date = models.DateField(verbose_name="Date d'émission")
    due_date = models.DateField(verbose_name="Date d'échéance")
    status = models.CharField(
        max_length=20,
        choices=InvoiceStatus.choices,
        default=InvoiceStatus.EN_ATTENTE,
        db_index=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="invoices_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Facture"
        verbose_name_plural = "Factures"
        ordering = ["-issue_date"]
        indexes = [
            models.Index(fields=["status", "issue_date"]),
            models.Index(fields=["client_phone"]),
        ]

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = self.generate_reference()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.reference} — {self.client_name} ({self.amount:,.2f} FCFA)"

    @classmethod
    def generate_reference(cls) -> str:
        """Generate next invoice reference: FACT-YYYY-XXXX."""
        from datetime import date
        year = date.today().year
        prefix = f"FACT-{year}-"
        last = cls.objects.filter(reference__startswith=prefix).order_by("-reference").first()
        if last:
            try:
                seq = int(last.reference.split("-")[-1]) + 1
            except ValueError:
                seq = 1
        else:
            seq = 1
        return f"{prefix}{seq:04d}"


class Payment(models.Model):
    """
    Payment reçu — entité centrale du pipeline IA.

    RÈGLES D'OR :
    - provider_ref unique=True (anti-doublon natif au niveau DB)
    - amount DecimalField(14, 2) — jamais de FloatField
    - paid_at indexé pour optimiser les requêtes dashboard
    """
    provider_ref = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        verbose_name="Référence opérateur",
        help_text="Référence unique de la transaction Mobile Money.",
    )
    amount = models.DecimalField(
        max_digits=14, decimal_places=2, verbose_name="Montant (FCFA)"
    )
    channel = models.CharField(
        max_length=20, choices=Channel.choices, db_index=True, verbose_name="Canal"
    )
    payer_name = models.CharField(max_length=200, blank=True, default="", verbose_name="Payeur")
    payer_phone = models.CharField(max_length=20, blank=True, default="", verbose_name="Téléphone payeur")
    paid_at = models.DateTimeField(db_index=True, verbose_name="Date de paiement")

    # Preuve et traçabilité IA
    evidence_image = models.ImageField(
        upload_to="evidence/%Y/%m/", blank=True, null=True, verbose_name="Image de preuve"
    )
    raw_text = models.TextField(
        blank=True, default="", verbose_name="Texte brut extrait par l'IA"
    )
    ai_confidence = models.FloatField(
        default=0.0, verbose_name="Score de confiance IA (0-1)"
    )

    # Réconciliation
    match_method = models.CharField(
        max_length=20, choices=MatchMethod.choices, default=MatchMethod.MANUEL,
        verbose_name="Méthode de matching",
    )
    status = models.CharField(
        max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.NON_RATTACHE,
        db_index=True, verbose_name="Statut",
    )
    invoice = models.ForeignKey(
        Invoice, on_delete=models.PROTECT, null=True, blank=True,
        related_name="payments", verbose_name="Facture rapprochée",
    )
    anomaly_score = models.FloatField(default=0.0, verbose_name="Score d'anomalie (0-1)")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="payments_created", verbose_name="Saisi par",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Paiement"
        verbose_name_plural = "Paiements"
        ordering = ["-paid_at"]
        indexes = [
            models.Index(fields=["status", "paid_at"]),
            models.Index(fields=["channel", "paid_at"]),
            models.Index(fields=["anomaly_score"]),
        ]

    def __str__(self) -> str:
        return f"{self.provider_ref} — {self.amount:,.2f} FCFA ({self.get_channel_display()})"

    def clean(self):
        if self.amount <= Decimal("0"):
            raise ValidationError({"amount": "Le montant doit être strictement positif."})
        if not (0 <= self.ai_confidence <= 1):
            raise ValidationError({"ai_confidence": "Le score IA doit être entre 0 et 1."})


class Expense(models.Model):
    """Flux sortants — fournisseurs, salaires, loyer."""
    supplier = models.CharField(max_length=200, verbose_name="Fournisseur / Bénéficiaire")
    category = models.CharField(
        max_length=20, choices=ExpenseCategory.choices,
        default=ExpenseCategory.AUTRE, verbose_name="Catégorie",
    )
    amount = models.DecimalField(
        max_digits=14, decimal_places=2, verbose_name="Montant (FCFA)"
    )
    paid_at = models.DateTimeField(db_index=True, verbose_name="Date de paiement")
    receipt_image = models.ImageField(
        upload_to="expenses/%Y/%m/", blank=True, null=True, verbose_name="Justificatif"
    )
    note = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="expenses_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Dépense"
        verbose_name_plural = "Dépenses"
        ordering = ["-paid_at"]

    def __str__(self) -> str:
        return f"{self.supplier} — {self.amount:,.2f} FCFA ({self.get_category_display()})"


class ForecastCache(models.Model):
    """Cache des prévisions Holt-Winters (pré-calculées via generate_forecast)."""
    days = models.PositiveSmallIntegerField(unique=True, default=7)
    forecast_data = models.JSONField(default=list)
    confidence_low = models.JSONField(default=list)
    confidence_high = models.JSONField(default=list)
    generated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Cache prévision"
        verbose_name_plural = "Caches prévisions"

    def __str__(self) -> str:
        return f"Forecast J+{self.days} (généré {self.generated_at:%Y-%m-%d %H:%M})"


class GatewayTransactionStatus(models.TextChoices):
    PENDING = "PENDING", "En attente (push envoyé)"
    SUCCESS = "SUCCESS", "Succès"
    FAILED = "FAILED", "Échec"
    EXPIRED = "EXPIRED", "Expiré"


class GatewayTransaction(models.Model):
    """
    Demande de collecte Mobile Money (T-Money / Moov / Flooz).

    Flux : le Caissier demande le paiement d'une facture par téléphone du
    client → push USSD / API collection opérateur → le client valide sur
    son téléphone → le webhook opérateur (ou le polling) confirme SUCCESS.
    En sandbox (aucune clé configurée), la réponse est simulée de façon
    déterministe pour la démonstration.
    """
    invoice = models.ForeignKey(
        Invoice, on_delete=models.CASCADE, related_name="gateway_transactions",
        verbose_name="Facture à encaisser",
    )
    operator = models.CharField(max_length=20, choices=Channel.choices, verbose_name="Opérateur")
    phone = models.CharField(max_length=20, verbose_name="Téléphone débité")
    amount = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="Montant (FCFA)")
    gateway_tx_id = models.CharField(max_length=60, unique=True, db_index=True, verbose_name="ID opérateur")
    status = models.CharField(
        max_length=20, choices=GatewayTransactionStatus.choices,
        default=GatewayTransactionStatus.PENDING, db_index=True,
    )
    is_sandbox = models.BooleanField(default=True, verbose_name="Sandbox")
    raw_response = models.JSONField(default=dict, blank=True, verbose_name="Réponse brute opérateur")
    initiated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="gateway_transactions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Transaction passerelle"
        verbose_name_plural = "Transactions passerelles"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "created_at"])]

    def __str__(self) -> str:
        return f"{self.gateway_tx_id} — {self.amount:,.0f} FCFA ({self.operator}, {self.status})"
