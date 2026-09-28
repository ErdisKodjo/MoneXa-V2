"""
Tests API REST caisse (POS) — contrat de l'app mobile Flutter.

Couvre :
- catalogue produits + recherche
- session (GET null / POST ouverture / rapport X / clôture Z)
- ventes : POST idempotent, rendu espèces, erreurs métier → 400
- scoping RBAC (caissier = ses ventes, comptable+ = tout)
- authentification obligatoire (401)
"""
import uuid
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from caisse.models import Produit, SessionCaisse, SessionStatut, Vente
from caisse import services

pytestmark = pytest.mark.django_db

D = Decimal


@pytest.fixture
def c_gerant(gerant):
    client = APIClient()
    client.force_authenticate(user=gerant)
    return client


@pytest.fixture
def c_caissier(caissier):
    client = APIClient()
    client.force_authenticate(user=caissier)
    return client


@pytest.fixture
def c_anonyme():
    return APIClient()


@pytest.fixture
def produits(db):
    a = Produit.objects.create(
        designation="Sac de riz 50kg", prix_ttc=D("25000"), tva_taux=D("18.00"),
        stock=D("20"), seuil_alerte=D("5"), reference="ART-RIZ01", ean="1234567890123",
    )
    b = Produit.objects.create(
        designation="Huile 5L", prix_ttc=D("5000"), tva_taux=D("18.00"),
        stock=D("2"), seuil_alerte=D("5"), reference="ART-HUILE1",
    )
    return a, b


def _panier(produit, quantite="2"):
    return [{
        "produit_id": produit.pk, "quantite": quantite, "remise_pct": "0",
    }]


class TestAuthCaisse:
    def test_produits_exige_auth(self, c_anonyme):
        assert c_anonyme.get("/api/caisse/produits/").status_code == 401

    def test_session_exige_auth(self, c_anonyme):
        assert c_anonyme.get("/api/caisse/session/").status_code == 401

    def test_ventes_exige_auth(self, c_anonyme):
        assert c_anonyme.get("/api/caisse/ventes/").status_code == 401


class TestProduitsApi:
    def test_liste_active_uniquement(self, c_caissier, produits):
        a, b = produits
        b.actif = False
        b.save()
        resp = c_caissier.get("/api/caisse/produits/")
        assert resp.status_code == 200
        refs = [p["reference"] for p in resp.json()]
        assert refs == [a.reference]

    def test_recherche_ean_exact(self, c_caissier, produits):
        resp = c_caissier.get("/api/caisse/produits/?q=1234567890123")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["designation"] == "Sac de riz 50kg"

    def test_recherche_designation_partielle(self, c_caissier, produits):
        resp = c_caissier.get("/api/caisse/produits/?q=huile")
        assert resp.status_code == 200
        assert len(resp.json()) == 1


class TestSessionApi:
    def test_aucune_session(self, c_caissier):
        resp = c_caissier.get("/api/caisse/session/")
        assert resp.status_code == 200
        assert resp.json() == {"session": None, "rapport": None}

    def test_ouverture_fond_caisse(self, c_caissier):
        resp = c_caissier.post("/api/caisse/session/", {"fond_caisse": "5000"}, format="json")
        assert resp.status_code == 201
        assert resp.json()["statut"] == "OUVERTE"
        assert resp.json()["fond_caisse"] == "5000.00"

    def test_ouverture_double_refusee(self, c_caissier):
        c_caissier.post("/api/caisse/session/", {"fond_caisse": "0"}, format="json")
        resp = c_caissier.post("/api/caisse/session/", {"fond_caisse": "0"}, format="json")
        assert resp.status_code == 400

    def test_fond_caisse_invalide(self, c_caissier):
        resp = c_caissier.post("/api/caisse/session/", {"fond_caisse": "abc"}, format="json")
        assert resp.status_code == 400

    def test_rapport_x(self, c_caissier, produits):
        a, _ = produits
        c_caissier.post("/api/caisse/session/", {"fond_caisse": "1000"}, format="json")
        c_caissier.post("/api/caisse/ventes/", {
            "lignes": _panier(a),
            "paiements": [{"moyen": "ESPECES", "montant": "60000"}],
        }, format="json")
        resp = c_caissier.get("/api/caisse/session/")
        body = resp.json()
        assert body["session"]["statut"] == "OUVERTE"
        rapport = body["rapport"]
        assert rapport["nb_tickets"] == 1
        assert rapport["total_ttc"] == "50000.00"
        # Sémantique web conservée : par_moyen = brut encaissé (rendu inclus),
        # especes_theorique = net réellement en caisse (fond + ventes − rendu).
        moyens = {m["moyen"]: m for m in rapport["par_moyen"]}
        assert moyens["ESPECES"]["montant"] == "60000.00"
        assert moyens["ESPECES"]["nb"] == 1
        # fond_caisse 1000 + net espèces 50000 (rendu 10000 déjà déduit)
        assert rapport["especes_theorique"] == "51000.00"

    def test_cloture_z_avec_ecart(self, c_caissier):
        c_caissier.post("/api/caisse/session/", {"fond_caisse": "5000"}, format="json")
        resp = c_caissier.post(
            "/api/caisse/session/cloture/",
            {"comptage_physique": "4800", "note": "Test écart"},
            format="json",
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["statut"] == "FERMEE"
        assert body["ecart"] == "-200.00"
        # Plus de session ouverte après clôture
        assert c_caissier.get("/api/caisse/session/").json()["session"] is None

    def test_cloture_sans_session(self, c_caissier):
        resp = c_caissier.post(
            "/api/caisse/session/cloture/", {"comptage_physique": "0"}, format="json"
        )
        assert resp.status_code == 400


class TestVentesApi:
    def test_vente_especes_avec_rendu(self, c_caissier, produits):
        a, _ = produits
        c_caissier.post("/api/caisse/session/", {"fond_caisse": "0"}, format="json")
        resp = c_caissier.post("/api/caisse/ventes/", {
            "lignes": _panier(a),
            "paiements": [{"moyen": "ESPECES", "montant": "60000"}],
            "idempotence_key": str(uuid.uuid4()),
        }, format="json")
        assert resp.status_code == 201
        body = resp.json()
        assert body["created"] is True
        assert body["total_ttc"] == "50000.00"
        assert body["rendu"] == "10000.00"
        assert len(body["lignes"]) == 1
        # Stock décrémenté
        a.refresh_from_db()
        assert a.stock == D("18")

    def test_vente_idempotente_pas_de_doublon(self, c_caissier, produits):
        a, _ = produits
        c_caissier.post("/api/caisse/session/", {"fond_caisse": "0"}, format="json")
        key = str(uuid.uuid4())
        payload = {
            "lignes": _panier(a),
            "paiements": [{"moyen": "TMONEY", "montant": "50000"}],
            "idempotence_key": key,
        }
        r1 = c_caissier.post("/api/caisse/ventes/", payload, format="json")
        r2 = c_caissier.post("/api/caisse/ventes/", payload, format="json")
        assert r1.status_code == 201
        assert r2.status_code == 200
        assert r1.json()["reference"] == r2.json()["reference"]
        assert r2.json()["created"] is False
        assert Vente.objects.count() == 1

    def test_vente_sans_session_refusee(self, c_caissier, produits):
        a, _ = produits
        resp = c_caissier.post("/api/caisse/ventes/", {
            "lignes": _panier(a),
            "paiements": [{"moyen": "ESPECES", "montant": "25000"}],
        }, format="json")
        assert resp.status_code == 400
        assert "session" in resp.json()["detail"].lower()

    def test_vente_sous_payee_refusee(self, c_caissier, produits):
        a, _ = produits
        c_caissier.post("/api/caisse/session/", {"fond_caisse": "0"}, format="json")
        resp = c_caissier.post("/api/caisse/ventes/", {
            "lignes": _panier(a, quantite="2"),
            "paiements": [{"moyen": "ESPECES", "montant": "10000"}],
        }, format="json")
        assert resp.status_code == 400
        assert "Encaissement incomplet" in resp.json()["detail"]

    def test_panier_vide_refuse(self, c_caissier):
        c_caissier.post("/api/caisse/session/", {"fond_caisse": "0"}, format="json")
        resp = c_caissier.post("/api/caisse/ventes/", {
            "lignes": [],
            "paiements": [{"moyen": "ESPECES", "montant": "1000"}],
        }, format="json")
        assert resp.status_code == 400

    def test_remise_caissier_depasse_plafond(self, c_caissier, produits):
        a, _ = produits
        c_caissier.post("/api/caisse/session/", {"fond_caisse": "0"}, format="json")
        resp = c_caissier.post("/api/caisse/ventes/", {
            "lignes": _panier(a),
            "paiements": [{"moyen": "ESPECES", "montant": "50000"}],
            "remise_panier_pct": "30",
        }, format="json")
        assert resp.status_code == 400
        assert "Remise" in resp.json()["detail"]

    def test_produit_inconnu(self, c_caissier):
        c_caissier.post("/api/caisse/session/", {"fond_caisse": "0"}, format="json")
        resp = c_caissier.post("/api/caisse/ventes/", {
            "lignes": [{"produit_id": 99999, "quantite": "1"}],
            "paiements": [{"moyen": "ESPECES", "montant": "1000"}],
        }, format="json")
        assert resp.status_code == 400

    def test_scoping_caissier_voit_ses_ventes(self, c_caissier, c_gerant, produits):
        a, _ = produits
        # Vente du caissier sur sa propre session
        c_caissier.post("/api/caisse/session/", {"fond_caisse": "0"}, format="json")
        c_caissier.post("/api/caisse/ventes/", {
            "lignes": _panier(a),
            "paiements": [{"moyen": "ESPECES", "montant": "50000"}],
        }, format="json")
        # Le gérant (comptable+) voit la vente
        resp_gerant = c_gerant.get("/api/caisse/ventes/")
        assert resp_gerant.status_code == 200
        assert len(resp_gerant.json()) == 1
        # Un second caissier ne voit rien
        from accounts.models import Role, User
        autre = User.objects.create_user(
            email="autre@test.tg", password="Testpass123!", role=Role.CAISSIER,
        )
        client_autre = APIClient()
        client_autre.force_authenticate(user=autre)
        assert client_autre.get("/api/caisse/ventes/").json() == []

    def test_filtre_statut(self, c_caissier, c_gerant, gerant, produits):
        a, _ = produits
        c_caissier.post("/api/caisse/session/", {"fond_caisse": "0"}, format="json")
        c_caissier.post("/api/caisse/ventes/", {
            "lignes": _panier(a),
            "paiements": [{"moyen": "ESPECES", "montant": "50000"}],
        }, format="json")
        vente = Vente.objects.first()
        assert vente is not None
        services.annuler_vente(vente, user=gerant)
        resp = c_gerant.get("/api/caisse/ventes/?statut=ANNULEE")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert c_gerant.get("/api/caisse/ventes/?statut=VALIDEE").json() == []
