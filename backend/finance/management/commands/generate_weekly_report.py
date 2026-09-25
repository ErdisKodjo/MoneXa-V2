"""
Commande : generate_weekly_report — rapport hebdomadaire du CFO virtuel.

Usage :
    python manage.py generate_weekly_report              # rapport + notification
    python manage.py generate_weekly_report --no-llm     # synthèse déterministe
    python manage.py generate_weekly_report --print      # affiche sans notifier

À planifier (cron / celery beat / Render cron) :
    0 8 * * 1   → chaque lundi 08:00 (Africa/Lome)
"""
from django.core.management.base import BaseCommand

from finance.services.weekly_report import (
    _weekly_facts,
    generate_weekly_report,
)


class Command(BaseCommand):
    help = "Génère le rapport hebdomadaire du CFO virtuel (LLM si clé, sinon synthèse déterministe)."

    def add_arguments(self, parser):
        parser.add_argument("--no-llm", action="store_true", help="Force le template déterministe")
        parser.add_argument("--print", action="store_true", help="Affiche sans créer de notification")

    def handle(self, *args, **options):
        if options["print"]:
            # Génération seule : jamais de double appel LLM
            facts = _weekly_facts()
            text, source = generate_weekly_report(use_llm=not options["no_llm"])
        else:
            # Génère ET livre en notification aux Gérants (un seul appel)
            from finance.services.weekly_report import deliver_weekly_report

            text, source = deliver_weekly_report()
            facts = _weekly_facts()

        self.stdout.write(self.style.NOTICE(f"Rapport hebdomadaire [{source}]"))
        self.stdout.write(f"Période : {facts['periode']}")
        self.stdout.write(self.style.MIGRATE_HEADING("─" * 62))
        self.stdout.write(text)
        self.stdout.write(self.style.MIGRATE_HEADING("─" * 62))
        if options["print"]:
            self.stdout.write("Mode --print : aucune notification créée.")
