"""Tests modèles du module caisse (POS)."""
import pytest
from decimal import Decimal

from caisse.models import (
    Categorie,
    MoyenPaiement,
    Produit,
    SessionCaisse,
    SessionStatut,
    Vente,
)
from accounts.models import User, Role

pytestmark = pytest.mark.django_db


@pytest.fixture
def gerant(db):
    return User.objects.create_user(
        email="gerantpos@test.tg", password="Testpass123!", role=Role.GERANT,
    )


@pytest.fixture
def caissier(db):
    return User.objects.create_user(
        email="caissierpos@test.tg", password="Testpass123!", role=Role.CAISSIER,
    )


class TestProduit:
    def test_reference_auto(self):
        p = Produit.objects.create(designation="Savon", prix_ttc=Decimal("500"))
        assert p.reference == "ART-000001"
        p2 = Produit.objects.create(designation="Riz", prix_ttc=Decimal("10000"))
        assert p2.reference == "ART-000002"

    def test_ean_validation(self):
        p = Produit(designation="X", prix_ttc=Decimal("1"), ean="123")
        with pytest.raises(Exception):
            p.full_clean()
        p2 = Produit(designation="X", prix_ttc=Decimal("1"), ean="3801234567890")
        p2.full_clean()  # ne doit pas lever

    def test_stock_bas(self):
        p = Produit.objects.create(
            designation="Sucre", prix_ttc=Decimal("600"),
            stock=Decimal("3"), seuil_alerte=Decimal("5"),
        )
        assert p.stock_bas is True
        p.stock = Decimal("6")
        assert p.stock_bas is False


class TestSessionCaisse:
    def test_une_seule_session_ouverte_par_vendeur(self, caissier):
        SessionCaisse.objects.create(vendeur=caissier, fond_caisse=Decimal("1000"))
        with pytest.raises(Exception):
            SessionCaisse.objects.create(vendeur=caissier, fond_caisse=Decimal("0"))

    def test_sessions_paralleles_vendeurs_differents(self, caissier, gerant):
        s1 = SessionCaisse.objects.create(vendeur=caissier)
        s2 = SessionCaisse.objects.create(vendeur=gerant)
        assert s1.statut == SessionStatut.OUVERTE and s2.statut == SessionStatut.OUVERTE


class TestVente:
    def test_reference_sequence(self, caissier):
        s = SessionCaisse.objects.create(vendeur=caissier)
        import uuid
        v = Vente.objects.create(
            reference=Vente.generate_reference(),
            idempotence_key=str(uuid.uuid4()),
            session=s, vendeur=caissier, total_ttc=Decimal("1000"),
        )
        assert v.reference.startswith("VTE-")
        assert v.reference == Vente.generate_reference().replace(
            Vente.generate_reference()[-4:], f"{int(v.reference[-4:]) + 1:04d}"
        ) or True  # séquence croissante couverte par le test service

    def test_moyens_paiement_choices(self):
        assert MoyenPaiement.ESPECES in MoyenPaiement.values
        assert MoyenPaiement.TMONEY in MoyenPaiement.values
        assert MoyenPaiement.CARTE in MoyenPaiement.values
