"""
MoneXa User model — Custom User with RBAC roles.

Three roles (RBAC):
- CAISSIER  : terrain (saisie mobile, ses propres paiements)
- COMPTABLE : back-office (validation A_VALIDER, exports)
- GERANT    : autorité complète (anomalies, audit, users, 2FA)
"""
from django.contrib.auth.models import AbstractUser
from django.db import models
from .managers import UserManager


class Role(models.TextChoices):
    GERANT = "GERANT", "Gérant"
    COMPTABLE = "COMPTABLE", "Comptable"
    CAISSIER = "CAISSIER", "Caissier"


class User(AbstractUser):
    # USERNAME_FIELD = email (username kept for Django Admin compatibility but
    # email is the real login identifier)
    username = models.CharField(max_length=150, blank=True, null=True)
    email = models.EmailField(unique=True, db_index=True)

    # RBAC
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.CAISSIER,
        db_index=True,
    )

    # Mobile Money phone (T-Money / Moov / Flooz)
    phone = models.CharField(max_length=20, blank=True, default="")

    # 2FA TOTP — optionnel pour le Gérant
    is_2fa_enabled = models.BooleanField(default=False)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["role"]

    objects = UserManager()

    class Meta:
        verbose_name = "utilisateur"
        verbose_name_plural = "utilisateurs"
        ordering = ["-date_joined"]

    def __str__(self) -> str:
        return f"{self.email} ({self.get_role_display()})"

    # ── Helpers RBAC ────────────────────────────────────────────────────
    def is_gerant(self) -> bool:
        return self.role == Role.GERANT or self.is_superuser

    def is_comptable_or_higher(self) -> bool:
        return self.is_gerant() or self.role == Role.COMPTABLE

    def is_caissier_or_higher(self) -> bool:
        return self.is_comptable_or_higher() or self.role == Role.CAISSIER

    @property
    def display_name(self) -> str:
        if self.get_full_name():
            return self.get_full_name()
        return self.email


class Notification(models.Model):
    """
    Notification in-app (cloche web) — rappels factures impayées, alertes
    passerelles, décisions de validation. Un jour : relai FCM/SMS.
    """
    KIND_CHOICES = [
        ("RAPPEL_FACTURE", "Rappel facture impayée"),
        ("PASSERELLE", "Passerelle Mobile Money"),
        ("ANOMALIE", "Anomalie détectée"),
        ("VALIDATION", "Paiement à valider"),
        ("INFO", "Information"),
    ]
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="notifications", verbose_name="Destinataire"
    )
    kind = models.CharField(max_length=30, choices=KIND_CHOICES, default="INFO", db_index=True)
    title = models.CharField(max_length=200, verbose_name="Titre")
    body = models.TextField(blank=True, default="", verbose_name="Message")
    url = models.CharField(
        max_length=200, blank=True, default="",
        help_text="Lien interne (ex. /factures/) cliquable depuis la cloche.",
    )
    is_read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "notification"
        verbose_name_plural = "notifications"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "is_read"])]

    def __str__(self) -> str:
        return f"{self.title} → {self.user.email}"
