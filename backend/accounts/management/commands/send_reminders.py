"""
send_reminders - notifications de rappel in-app (cron-able).

Cree des notifications pour :
1. Les factures EN_ATTENTE echues (due_date < aujourd'hui) -> destinataires :
   Comptables + Gerants.
2. Les paiements A_VALIDER en attente de decision comptable.

Deduplication : pas de nouvelle notification si le meme (user, titre)
est deja present non lu. Idempotent - peut tourner toutes les heures.

Usage : python manage.py send_reminders
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import Notification
from finance.models import Invoice, InvoiceStatus, Payment, PaymentStatus


class Command(BaseCommand):
    help = "Cree les notifications de rappel (factures echues, paiements a valider)."

    def handle(self, *args, **options):
        User = get_user_model()
        managers = User.objects.filter(
            role__in=["COMPTABLE", "GERANT"], is_active=True
        )
        created = 0
        today = timezone.localdate()

        # 1 - Factures echues
        at_risk = Invoice.objects.filter(status=InvoiceStatus.EN_ATTENTE)
        for invoice in at_risk:
            days_late = (today - invoice.due_date).days
            if days_late < 0:
                continue  # echeance future
            if days_late == 0:
                title = f"Facture {invoice.reference} due aujourd'hui"
                body = (
                    f"{invoice.client_name} doit {invoice.amount:,.0f} FCFA - "
                    "lancez un encaissement Mobile Money depuis /encaissements/."
                )
            else:
                title = f"Facture {invoice.reference} en retard de {days_late} j"
                body = (
                    f"{invoice.client_name} - {invoice.amount:,.0f} FCFA impayes "
                    f"depuis le {invoice.due_date:%d/%m/%Y}. Relancez le client."
                )
            for user in managers:
                _, was_created = Notification.objects.get_or_create(
                    user=user, kind="RAPPEL_FACTURE", title=title,
                    defaults={"body": body, "url": "/factures/"},
                )
                created += 1 if was_created else 0

        # 2 - Paiements a valider (file comptable)
        pending = Payment.objects.filter(status=PaymentStatus.A_VALIDER).count()
        if pending:
            title = f"{pending} paiement(s) en attente de validation"
            body = "Ouvrez /paiements/ et traitez la file A_VALIDER."
            for user in managers:
                _, was_created = Notification.objects.get_or_create(
                    user=user, kind="VALIDATION", title=title,
                    defaults={"body": body, "url": "/paiements/"},
                )
                created += 1 if was_created else 0

        self.stdout.write(
            self.style.SUCCESS(f"send_reminders : {created} notification(s) creee(s).")
        )
