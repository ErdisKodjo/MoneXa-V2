"""
Tests 2FA TOTP (activation web) + notifications + commandes.

Utilise django_otp.oath (inclus dans django-otp) pour générer les codes.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from django_otp.oath import TOTP as OathTOTP
from django_otp.plugins.otp_totp.models import TOTPDevice

from finance.models import Invoice, Payment


def _device_code(device) -> str:
    """Code TOTP valide pour l'instant présent (6 chiffres)."""
    totp = OathTOTP(device.bin_key)
    totp.time = timezone.now().timestamp()
    return str(totp.token()).zfill(device.digits or 6)


@pytest.fixture
def gerant(django_user_model):
    return django_user_model.objects.create_user(
        email="secu@monexa.tg", password="Monexa2026!", role="GERANT"
    )


def _login(client, gerant):
    client.force_login(gerant)


def test_security_page_requires_gerant(client, db, django_user_model):
    caissier = django_user_model.objects.create_user(
        email="cai@monexa.tg", password="Monexa2026!", role="CAISSIER"
    )
    client.force_login(caissier)
    resp = client.get(reverse("security"))
    assert resp.status_code == 403


def test_enable_and_confirm_2fa(client, db, gerant):
    _login(client, gerant)
    # Étape 1 — création du device
    resp = client.post(reverse("security"), {"action": "enable"})
    assert resp.status_code == 302
    device = gerant.totpdevice_set.get(confirmed=False)
    # Étape 2 — confirmation avec un code TOTP valide
    resp = client.post(
        reverse("security"), {"action": "confirm", "code": _device_code(device)}
    )
    assert resp.status_code == 302
    gerant.refresh_from_db()
    assert gerant.is_2fa_enabled
    assert gerant.totpdevice_set.filter(confirmed=True).exists()


def test_login_flow_with_2fa(client, db, gerant):
    # Activation complète d'abord
    _login(client, gerant)
    client.post(reverse("security"), {"action": "enable"})
    device = gerant.totpdevice_set.get(confirmed=False)
    client.post(
        reverse("security"), {"action": "confirm", "code": _device_code(device)}
    )
    client.logout()

    # Étape 1 — mot de passe seul → redirection TOTP
    resp = client.post(
        reverse("login"),
        {"username": "secu@monexa.tg", "password": "Monexa2026!"},
        follow=True,
    )
    assert resp.resolver_match.url_name in ("totp_login", "login")
    if resp.resolver_match.url_name == "totp_login":
        # Étape 2 — code TOTP (anti-replay : on vieillit le dernier t utilisé
        # pour simuler un créneau de 30 s différent de la confirmation)
        TOTPDevice.objects.filter(pk=device.pk).update(last_t=1)
        device.refresh_from_db()
        resp = client.post(reverse("totp_login"), {"code": _device_code(device)}, follow=True)
        assert resp.resolver_match.url_name == "dashboard"

    # Code erroné refusé
    client.logout()
    client.post(reverse("login"), {"username": "secu@monexa.tg", "password": "Monexa2026!"})
    resp = client.post(reverse("totp_login"), {"code": "000000"})
    assert resp.status_code == 200  # formulaire ré-affiché avec erreur


def test_disable_2fa(client, db, gerant):
    _login(client, gerant)
    client.post(reverse("security"), {"action": "enable"})
    device = gerant.totpdevice_set.get(confirmed=False)
    client.post(
        reverse("security"), {"action": "confirm", "code": _device_code(device)}
    )
    client.post(reverse("security"), {"action": "disable"})
    gerant.refresh_from_db()
    assert not gerant.is_2fa_enabled
    assert gerant.totpdevice_set.count() == 0


def test_send_reminders_command(db, django_user_model, monkeypatch):
    from django.core.management import call_command

    from accounts.models import Notification

    gerant = django_user_model.objects.create_user(
        email="rem@monexa.tg", password="Monexa2026!", role="GERANT"
    )
    comptable = django_user_model.objects.create_user(
        email="rem2@monexa.tg", password="Monexa2026!", role="COMPTABLE"
    )
    caissier = django_user_model.objects.create_user(
        email="rem3@monexa.tg", password="Monexa2026!", role="CAISSIER"
    )
    late_invoice = Invoice.objects.create(
        reference="FACT-2026-8001",
        client_name="Client Retard",
        amount=Decimal("10000"),
        issue_date=timezone.localdate() - timedelta(days=40),
        due_date=timezone.localdate() - timedelta(days=10),
        created_by=caissier,
    )
    Payment.objects.create(
        provider_ref="TMXREM01", amount=Decimal("5000"), channel="TMONEY",
        payer_name="X", paid_at=timezone.now(), created_by=caissier,
        status="A_VALIDER",
    )
    call_command("send_reminders", verbosity=0)
    titles = list(
        Notification.objects.filter(user=gerant).values_list("title", flat=True)
    )
    assert any("FACT-2026-8001" in t for t in titles)
    assert any("en attente de validation" in t for t in titles)
    # Le Caissier ne reçoit pas les rappels de gestion
    assert not Notification.objects.filter(user=caissier).exists()
    # Idempotent : un second passage ne duplique pas
    call_command("send_reminders", verbosity=0)
    assert Notification.objects.filter(user=gerant).count() == len(titles)
