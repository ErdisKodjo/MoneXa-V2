"""
Management command: import_bank_statement

Importe un relevé bancaire CSV et le rapproche automatiquement des
factures impayées (rapprochement multi-comptes, v2.3).

Usage:
    python manage.py import_bank_statement chemin/vers/releve.csv
"""
from django.core.management.base import BaseCommand, CommandError

from finance.services.bank_reconcile import parse_bank_csv, reconcile_bank_statement


class Command(BaseCommand):
    help = "Rapproche un relevé bancaire CSV des factures impayées (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("csv_path", help="Chemin du fichier CSV du relevé.")
        parser.add_argument("--user-email", default="comptable@monexa.tg",
                            help="Email de l'utilisateur crédité de l'import.")

    def handle(self, *args, **options):
        from accounts.models import User

        path = options["csv_path"]
        try:
            with open(path, "rb") as fh:
                csv_bytes = fh.read()
        except OSError as exc:
            raise CommandError(f"Lecture impossible : {exc}")

        lines, errors, debits = parse_bank_csv(csv_bytes)
        user = User.objects.filter(email=options["user_email"]).first()
        if user is None:
            user = User.objects.filter(is_superuser=True).first()
        if user is None:
            raise CommandError("Aucun utilisateur trouvé — lancez d'abord seed_demo.")

        report = reconcile_bank_statement(
            lines, created_by=user, debits_ignored=debits, errors=errors,
        )
        self.stdout.write(self.style.SUCCESS(
            f"Import terminé : {report.imported} créé(s) — "
            f"ref {report.matched_ref} / montant {report.matched_amount} / "
            f"fuzzy {report.matched_fuzzy} / non rattachés {report.non_rattaches} / "
            f"doublons {report.skipped} / débits ignorés {report.debits_ignored}"
        ))
        for err in report.errors:
            self.stdout.write(self.style.WARNING(f"  ⚠ {err}"))
