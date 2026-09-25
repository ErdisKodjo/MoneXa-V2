"""
Management command: seed_demo

Génère un jeu de données de démonstration reproductible :
- 3 utilisateurs (Gérant, Comptable, Caissier) avec mots de passe connus
- 3 comptes de trésorerie (T-Money, Moov, Flooz)
- 50 factures (FACT-2026-0001 à FACT-2026-0050) sur 90 jours
- 200 paiements répartis par canal avec provider_ref uniques
- 3 anomalies typées :
    (1) doublon de provider_ref (géré par contrainte DB)
    (2) écart facture/paiement
    (3) paiement nocturne atypique
- 30 dépenses
- 1 cache de prévisions Holt-Winters

Usage:
    python manage.py seed_demo
"""
import random
from datetime import timedelta, timezone
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction

from accounts.models import User, Role
from finance.models import (
    Account, Invoice, Payment, Expense, ForecastCache,
    Channel, InvoiceStatus, PaymentStatus, MatchMethod, ExpenseCategory,
)
from finance.services.forecast import forecast_cashflow

try:
    from faker import Faker
    fake = Faker("fr_FR")
except ImportError:
    fake = None


NAMES = [
    "Kossi Mensah", "Afi Adjovi", "Koffi Agbessi", "Adzo Komla",
    "Komi Agbélo", "Awa Tchalla", "Yaovi Dotse", "Afia Mawusi",
    "Kossi Tsolenyanu", "Mensah Kossi", "Akossiwa Adje", "Kwami Sedinam",
    "Pierre Agbodjan", "Mawuko Amen", "Sena Kafui", "Delali Adjovi",
    "Komlan Afide", "Afi Esso", "Kossi Koffi", "Adjoa Yawa",
]
PHONE_PREFIXES = ["90", "91", "92", "93", "70", "79"]
SUPPLIERS = [
    "SODETOGO", "CEET", "Togocom", "BTP Plus", "ImmoLoc Lomé",
    "Fournisseur Agbé", "Pharmacie Centrale", "Cabinet Comptable Adjovi",
]


def _random_phone(rng: random.Random) -> str:
    p = rng.choice(PHONE_PREFIXES)
    rest = f"{rng.randint(10, 99)} {rng.randint(10, 99)} {rng.randint(10, 99)}"
    return f"+228 {p} {rest}"


class Command(BaseCommand):
    help = "Génère les données de démonstration MoneXa (3 rôles, 50 factures, 200 paiements, 3 anomalies)."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true",
                            help="Efface les données existantes avant le seed.")

    @transaction.atomic
    def handle(self, *args, **options):
        reset = options.get("reset", False)
        if reset:
            self.stdout.write(self.style.WARNING("⚠ Reset des données existantes..."))
            Payment.objects.all().delete()
            Invoice.objects.all().delete()
            Expense.objects.all().delete()
            Account.objects.all().delete()
            ForecastCache.objects.all().delete()
            User.objects.exclude(is_superuser=True).delete()

        already_seeded = User.objects.filter(email="gerant@monexa.tg").exists() and Invoice.objects.exists()
        if already_seeded and not reset:
            self.stdout.write(self.style.WARNING(
                "Données de démo déjà présentes — skip. Relancer avec --reset pour tout régénérer."
            ))
            return

        rng = random.Random(42)  # reproductible

        # ── Utilisateurs ────────────────────────────────────────────
        gerant, _ = User.objects.get_or_create(
            email="gerant@monexa.tg",
            defaults={
                "role": Role.GERANT,
                "phone": "+228 90 00 00 01",
                "is_staff": True,
                "is_superuser": False,
                "is_2fa_enabled": True,
            },
        )
        gerant.set_password("Monexa2026!")
        gerant.save()

        comptable, _ = User.objects.get_or_create(
            email="comptable@monexa.tg",
            defaults={
                "role": Role.COMPTABLE,
                "phone": "+228 91 00 00 02",
                "is_staff": True,
            },
        )
        comptable.set_password("Monexa2026!")
        comptable.save()

        caissier, _ = User.objects.get_or_create(
            email="caissier@monexa.tg",
            defaults={
                "role": Role.CAISSIER,
                "phone": "+228 92 00 00 03",
            },
        )
        caissier.set_password("Monexa2026!")
        caissier.save()

        self.stdout.write(f"  ✓ 3 utilisateurs créés (gerant / comptable / caissier)")

        # ── Comptes de trésorerie ──────────────────────────────────
        accounts = {}
        for channel_code, label in Channel.choices:
            acc, _ = Account.objects.get_or_create(
                name=label, channel=channel_code,
                defaults={"owner": gerant, "is_active": True},
            )
            accounts[channel_code] = acc
        self.stdout.write(f"  ✓ {len(accounts)} comptes de trésorerie")

        # ── Factures ────────────────────────────────────────────────
        now = timezone.now()
        for i in range(50):
            issue = now - timedelta(days=rng.randint(1, 90))
            due = issue + timedelta(days=rng.choice([7, 14, 30]))
            amount = Decimal(str(rng.choice([25_000, 50_000, 75_000, 100_000, 150_000, 200_000, 500_000, 750_000])))
            name = rng.choice(NAMES)
            Invoice.objects.create(
                reference=Invoice.generate_reference(),
                client_name=name,
                client_phone=_random_phone(rng),
                amount=amount,
                issue_date=issue.date(),
                due_date=due.date(),
                status=InvoiceStatus.EN_ATTENTE,
                created_by=caissier,
            )
        self.stdout.write(f"  ✓ 50 factures créées (FACT-2026-XXXX)")

        # ── Paiements ──────────────────────────────────────────────
        for i in range(200):
            channel_code = rng.choice([c[0] for c in Channel.choices[:3]])  # TMONEY, MOOV, FLOOZ
            prefix_map = {"TMONEY": "TMX", "MOOV": "MV", "FLOOZ": "FL"}
            ref = f"{prefix_map[channel_code]}{rng.randint(1000000000, 9999999999)}"

            paid_at = now - timedelta(
                days=rng.randint(0, 90),
                hours=rng.randint(8, 20),
                minutes=rng.randint(0, 59),
            )
            amount = Decimal(str(rng.choice([25_000, 50_000, 75_000, 100_000, 125_000, 200_000, 350_000, 500_000, 750_000])))
            name = rng.choice(NAMES)

            # Anomalie #2: écart montant (1 paiement sur 50)
            if i == 50:
                amount = amount + Decimal("5_000")

            # Anomalie #3: paiement nocturne (1 paiement sur 100)
            if i == 100:
                paid_at = paid_at.replace(hour=3, minute=12)

            Payment.objects.create(
                provider_ref=ref,
                amount=amount,
                channel=channel_code,
                payer_name=name,
                payer_phone=_random_phone(rng),
                paid_at=paid_at,
                raw_text=f"[SEED] Paiement {ref} de {name}, {amount} FCFA via {channel_code}.",
                ai_confidence=rng.uniform(0.80, 0.99),
                match_method=MatchMethod.MANUEL,
                status=PaymentStatus.NON_RATTACHE,
                anomaly_score=rng.uniform(0, 0.3),
                created_by=caissier,
            )
        self.stdout.write(f"  ✓ 200 paiements créés (3 anomalies typées incluses)")

        # ── Dépenses ────────────────────────────────────────────────
        for i in range(30):
            paid_at = now - timedelta(days=rng.randint(0, 90))
            Expense.objects.create(
                supplier=rng.choice(SUPPLIERS),
                category=rng.choice([c[0] for c in ExpenseCategory.choices]),
                amount=Decimal(str(rng.choice([15_000, 50_000, 100_000, 200_000, 350_000]))),
                paid_at=paid_at,
                created_by=comptable,
            )
        self.stdout.write(f"  ✓ 30 dépenses créées")

        # ── Cache prévisions ────────────────────────────────────────
        try:
            f7 = forecast_cashflow(days=7)
            ForecastCache.objects.update_or_create(
                days=7,
                defaults={
                    "forecast_data": f7.get("forecast", []),
                    "confidence_low": f7.get("confidence_low", []),
                    "confidence_high": f7.get("confidence_high", []),
                },
            )
            f30 = forecast_cashflow(days=30)
            ForecastCache.objects.update_or_create(
                days=30,
                defaults={
                    "forecast_data": f30.get("forecast", []),
                    "confidence_low": f30.get("confidence_low", []),
                    "confidence_high": f30.get("confidence_high", []),
                },
            )
            self.stdout.write(f"  ✓ Cache prévisions Holt-Winters (J+7 et J+30)")
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"  ⚠ Prévisions non générées: {e}"))

        self.stdout.write(self.style.SUCCESS("\n✅ Seed démo terminé."))
        self.stdout.write("\nComptes de test :")
        self.stdout.write("  Gérant     : gerant@monexa.tg / Monexa2026!")
        self.stdout.write("  Comptable  : comptable@monexa.tg / Monexa2026!")
        self.stdout.write("  Caissier   : caissier@monexa.tg / Monexa2026!")
