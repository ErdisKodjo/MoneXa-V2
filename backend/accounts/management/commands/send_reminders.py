"""
send_reminders - notifications de rappel in-app (cron-able).

Cree des notifications pour :
1. Les factures EN_ATTENTE echues (due_date <= aujourd'hui) -> destinataires :
   Comptables + Gerants. Corps court operationnel.
2. Les factures impayees depuis PLUS de --days jours (defaut 7) -> relance
   avec message redige par l'IA (TresorIA) si une cle API est configuree,
   sinon template deterministe (v2.3).
3. Les paiements A_VALIDER en attente de decision comptable.

Deduplication : pas de nouvelle notification si le meme (user, titre)
est deja present. Idempotent - peut tourner toutes les heures.

Usage :
    python manage.py send_reminders
    python manage.py send_reminders --days=7
    python manage.py send_reminders --dry-run     # apercu sans ecriture
    python manage.py send_reminders --no-llm      # template deterministe
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import Notification
from finance.models import Invoice, InvoiceStatus, Payment, PaymentStatus
from finance.services.reminders import JOURS_APRES_ECHEANCE, build_reminder_message


class Command(BaseCommand):
    help = "Cree les notifications de rappel (factures echues, relances IA > N jours, paiements a valider)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days", type=int, default=JOURS_APRES_ECHEANCE,
            help="Seuil de retard pour les relances IA (defaut 7)",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Affiche les messages sans creer de notification",
        )
        parser.add_argument(
            "--no-llm", action="store_true",
            help="Force le template deterministe (pas d'appel LLM)",
        )

    def handle(self, *args, **options):
        User = get_user_model()
        managers = list(
            User.objects.filter(role__in=["COMPTABLE", "GERANT"], is_active=True)
        )
        days = max(1, options["days"])
        dry_run = options["dry_run"]
        use_llm = not options["no_llm"]
        created = 0
        today = timezone.localdate()

        def _notify(user, kind, title, body, url):
            nonlocal created
            if dry_run:
                return
            _, was_created = Notification.objects.get_or_create(
                user=user, kind=kind, title=title,
                defaults={"body": body, "url": url},
            )
            created += 1 if was_created else 0

        at_risk = Invoice.objects.filter(status=InvoiceStatus.EN_ATTENTE)
        seuil_relance = today - timezone.timedelta(days=days)
        relances = []

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
                for user in managers:
                    _notify(user, "RAPPEL_FACTURE", title, body, "/factures/")
            elif invoice.due_date < seuil_relance:
                # Relance IA (v2.3) — message redige par LLM ou template
                message, source = build_reminder_message(invoice, use_llm=use_llm)
                title = (
                    f"Relance IA {invoice.reference} ({days_late} j de retard)"
                )
                relances.append((invoice, message, source))
                for user in managers:
                    _notify(user, "RAPPEL_FACTURE", title, message, "/factures/")
            else:
                title = f"Facture {invoice.reference} en retard de {days_late} j"
                body = (
                    f"{invoice.client_name} - {invoice.amount:,.0f} FCFA impayes "
                    f"depuis le {invoice.due_date:%d/%m/%Y}. Relancez le client."
                )
                for user in managers:
                    _notify(user, "RAPPEL_FACTURE", title, body, "/factures/")

        # Paiements a valider (file comptable)
        pending = Payment.objects.filter(status=PaymentStatus.A_VALIDER).count()
        if pending:
            title = f"{pending} paiement(s) en attente de validation"
            body = "Ouvrez /paiements/ et traitez la file A_VALIDER."
            for user in managers:
                _notify(user, "VALIDATION", title, body, "/paiements/")

        mode = "APERÇU (dry-run)" if dry_run else f"{created} notification(s) creee(s)"
        self.stdout.write(self.style.SUCCESS(f"send_reminders : {mode}."))
        for invoice, message, source in relances:
            self.stdout.write(
                f"  • Relance {invoice.reference} — {invoice.client_name} "
                f"[{source}] : {message[:120]}{'…' if len(message) > 120 else ''}"
            )
