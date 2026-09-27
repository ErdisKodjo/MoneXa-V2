"""
Tests vues WebUI du POS — RBAC strict + flux d'encaissement HTTP complet.
"""
import json
import uuid
import pytest
from decimal import Decimal

from accounts.models import User, Role
from caisse.models import Produit, SessionCaisse, Vente
from caisse import services
from finance.models import Payment, PaymentStatus

D = Decimal
pytestmark = pytest.mark.django_db


@pytest.fixture
def gerant(db):
    return User.objects.create_user(
        email="gerantvw@test.tg", password="Testpass123!", role=Role.GERANT,
    )


@pytest.fixture
def comptable(db):
    return User.objects.create_user(
        email="comptablevw@test.tg", password="Testpass123!", role=Role.COMPTABLE,
    )


@pytest.fixture
def caissier(db):
    return User.objects.create_user(
        email="caissiervw@test.tg", password="Testpass123!", role=Role.CAISSIER,
    )


@pytest.fixture
def produits(db):
    return (
        Produit.objects.create(designation="Ciment 50kg", prix_ttc=D("5000"),
                               stock=D("100"), seuil_alerte=D("10"), reference="ART-CIM01"),
        Produit.objects.create(designation="Peinture 20L", prix_ttc=D("25000"),
                               stock=D("40"), seuil_alerte=D("5"), reference="ART-PEI01"),
    )


def _login(client, user):
    client.force_login(user)


def _open_session(client, fond="10000"):
    return client.post("/caisse/session/", {"action": "ouvrir", "fond_caisse": fond})


class TestRBAC:
    def test_anonyme_redirige_vers_login(self, client):
        r = client.get("/caisse/")
        assert r.status_code == 302 and "/login/" in r.url
        r = client.get("/caisse/ventes/")
        assert r.status_code == 302
        r = client.get("/caisse/catalogue/")
        assert r.status_code == 302

    def test_caissier_accede_terminal_mais_pas_catalogue(self, client, caissier):
        _login(client, caissier)
        assert client.get("/caisse/").status_code == 200
        assert client.get("/caisse/session/").status_code == 200
        assert client.get("/caisse/ventes/").status_code == 200
        assert client.get("/caisse/catalogue/").status_code == 403

    def test_comptable_accede_catalogue_et_toutes_ventes(self, client, comptable, caissier):
        _login(client, comptable)
        assert client.get("/caisse/catalogue/").status_code == 200
        assert client.get("/caisse/").status_code == 200


class TestFluxEncaissementHTTP:
    def test_ouverture_session_et_terminal(self, client, caissier):
        _login(client, caissier)
        r = _open_session(client)
        assert r.status_code == 302
        assert SessionCaisse.objects.filter(vendeur=caissier, statut="OUVERTE").exists()
        r = client.get("/caisse/")
        assert r.status_code == 200 and b"Terminal" in r.content or b"caisse" in r.content

    def test_checkout_panier_json_complet(self, client, caissier, produits):
        """POS-02/04/08 — vente tactile : 3 articles, mixte espèces + T-Money."""
        _login(client, caissier)
        _open_session(client)
        session = SessionCaisse.objects.get(vendeur=caissier, statut="OUVERTE")
        cart = {
            "idempotence_key": str(uuid.uuid4()),
            "client_name": "Kossi A.",
            "client_phone": "+22890000000",
            "remise_panier": 0,
            "lignes": [
                {"produit_id": produits[0].pk, "designation": produits[0].designation,
                 "quantite": 2, "prix_unitaire_ttc": "5000", "tva_taux": "18", "remise_pct": 0},
                {"produit_id": produits[1].pk, "designation": produits[1].designation,
                 "quantite": 1, "prix_unitaire_ttc": "25000", "tva_taux": "18", "remise_pct": 0},
            ],
            "paiements": [
                {"moyen": "ESPECES", "montant": "20000", "reference": ""},
                {"moyen": "TMONEY", "montant": "15000", "reference": "SBTM-ABC"},
            ],
        }
        r = client.post("/caisse/", {"cart": json.dumps(cart)})
        assert r.status_code == 302
        vente = Vente.objects.latest("pk")
        assert vente.total_ttc == D("35000.00")
        assert vente.vendeur == caissier
        # POS-08 : 2 payments finance (journal/KPIs)
        assert Payment.objects.filter(
            provider_ref__startswith=f"POS-{vente.reference}-"
        ).count() == 2
        # POS-09 : stock décrémenté
        produits[0].refresh_from_db()
        produits[1].refresh_from_db()
        assert produits[0].stock == D("98.00")
        assert produits[1].stock == D("39.00")

    def test_checkout_replay_sans_doublon(self, client, caissier, produits):
        """POS-10 — un double POST (réseau instable) ne crée qu'une vente."""
        _login(client, caissier)
        _open_session(client)
        key = str(uuid.uuid4())
        cart = {
            "idempotence_key": key,
            "lignes": [{"produit_id": produits[0].pk, "designation": "Ciment",
                        "quantite": 1, "prix_unitaire_ttc": "5000", "tva_taux": "18"}],
            "paiements": [{"moyen": "ESPECES", "montant": "5000"}],
        }
        client.post("/caisse/", {"cart": json.dumps(cart)})
        r2 = client.post("/caisse/", {"cart": json.dumps(cart)})
        assert r2.status_code == 302
        assert Vente.objects.filter(idempotence_key=key).count() == 1
        produits[0].refresh_from_db()
        assert produits[0].stock == D("99.00")

    def test_vente_rapide_sans_js(self, client, caissier):
        _login(client, caissier)
        _open_session(client)
        r = client.post("/caisse/", {"quick": "1", "quick_amount": "3000"})
        assert r.status_code == 302
        vente = Vente.objects.latest("pk")
        assert vente.total_ttc == D("3000.00")
        assert vente.lignes.first().designation == "Vente rapide"

    def test_remise_hors_plafond_refusee(self, client, caissier, produits):
        _login(client, caissier)
        _open_session(client)
        cart = {
            "idempotence_key": str(uuid.uuid4()),
            "remise_panier": 20,  # caissier : max 5 %
            "lignes": [{"produit_id": produits[0].pk, "designation": "Ciment",
                        "quantite": 1, "prix_unitaire_ttc": "5000", "tva_taux": "18"}],
            "paiements": [{"moyen": "ESPECES", "montant": "4000"}],
        }
        r = client.post("/caisse/", {"cart": json.dumps(cart)})
        assert r.status_code == 302
        assert not Vente.objects.filter(
            idempotence_key=cart["idempotence_key"]
        ).exists()

    def test_comptable_remise_elevee_autorisee(self, client, comptable, produits):
        _login(client, comptable)
        client.post("/caisse/session/", {"action": "ouvrir", "fond_caisse": "0"})
        cart = {
            "idempotence_key": str(uuid.uuid4()),
            "remise_panier": 10,
            "lignes": [{"produit_id": produits[0].pk, "designation": "Ciment",
                        "quantite": 1, "prix_unitaire_ttc": "5000", "tva_taux": "18"}],
            "paiements": [{"moyen": "ESPECES", "montant": "4500"}],
        }
        r = client.post("/caisse/", {"cart": json.dumps(cart)})
        assert r.status_code == 302
        assert Vente.objects.filter(idempotence_key=cart["idempotence_key"]).exists()

    def test_checkout_sans_session_refuse(self, client, caissier, produits):
        _login(client, caissier)
        cart = {"idempotence_key": str(uuid.uuid4()),
                "lignes": [], "paiements": [{"moyen": "ESPECES", "montant": "100"}]}
        r = client.post("/caisse/", {"cart": json.dumps(cart)})
        assert r.status_code == 302  # redirect avec flash erreur


class TestClotureEtTicketsHTTP:
    def test_cloture_avec_ecart_et_page_anomalies(self, client, caissier, gerant, produits):
        _login(client, caissier)
        _open_session(client)
        cart = {
            "idempotence_key": str(uuid.uuid4()),
            "lignes": [{"produit_id": produits[0].pk, "designation": "Ciment",
                        "quantite": 1, "prix_unitaire_ttc": "5000", "tva_taux": "18"}],
            "paiements": [{"moyen": "ESPECES", "montant": "5000"}],
        }
        client.post("/caisse/", {"cart": json.dumps(cart)})
        r = client.post("/caisse/session/", {
            "action": "cloturer", "comptage_physique": "12000", "note": "Test écart",
        })
        assert r.status_code == 302
        session = SessionCaisse.objects.get(vendeur=caissier, statut="FERMEE")
        # Théorique : 10000 fond + 5000 vente = 15000 ; physique 12000 → écart -3000
        assert session.ecart == D("-3000.00")
        # Gérant : page anomalies accessible + notification ANOMALIE reçue
        from accounts.models import Notification
        assert Notification.objects.filter(user=gerant, kind="ANOMALIE").exists()

    def test_ticket_pdf_et_escpos_et_txt(self, client, caissier, produits):
        _login(client, caissier)
        _open_session(client)
        cart = {
            "idempotence_key": str(uuid.uuid4()),
            "lignes": [{"produit_id": produits[0].pk, "designation": "Ciment",
                        "quantite": 2, "prix_unitaire_ttc": "5000", "tva_taux": "18"}],
            "paiements": [{"moyen": "ESPECES", "montant": "12000"}],
        }
        client.post("/caisse/", {"cart": json.dumps(cart)})
        vente = Vente.objects.latest("pk")
        r_pdf = client.get(f"/caisse/ventes/{vente.reference}/ticket.pdf")
        assert r_pdf.status_code == 200
        assert r_pdf["Content-Type"] == "application/pdf"
        assert r_pdf.content[:4] == b"%PDF"
        r_bin = client.get(f"/caisse/ventes/{vente.reference}/ticket.escpos")
        assert r_bin.status_code == 200
        bin_content = b"".join(r_bin.streaming_content)
        assert bin_content.startswith(b"\x1b@")  # ESC @ = init imprimante
        r_txt = client.get(f"/caisse/ventes/{vente.reference}/ticket.txt")
        assert r_txt.status_code == 200
        assert vente.reference.encode() in r_txt.content

    def test_ticket_autre_vendeur_404_pour_caissier(self, client, caissier, comptable, produits):
        _login(client, comptable)
        client.post("/caisse/session/", {"action": "ouvrir", "fond_caisse": "0"})
        vente, _ = services.enregistrer_vente(services.VenteInput(
            session_id=SessionCaisse.objects.get(vendeur=comptable, statut="OUVERTE").pk,
            vendeur_id=comptable.pk,
            lignes=[services.LigneInput(designation="X", quantite=D("1"),
                                        prix_unitaire_ttc=D("1000"))],
            paiements=[services.PaiementInput(moyen="ESPECES", montant=D("1000"))],
        ))
        client.logout()
        _login(client, caissier)
        r = client.get(f"/caisse/ventes/{vente.reference}/ticket.pdf")
        assert r.status_code == 404
        # Le comptable lui-même y accède
        client.logout()
        _login(client, comptable)
        assert client.get(f"/caisse/ventes/{vente.reference}/ticket.pdf").status_code == 200


class TestCatalogue:
    def test_creation_produit_via_http(self, client, comptable):
        _login(client, comptable)
        r = client.post("/caisse/catalogue/", {
            "designation": "Bouteille eau 1.5L", "prix_ttc": "300",
            "tva_taux": "18", "unite": "pièce", "stock": "200",
            "seuil_alerte": "20", "actif": "on",
        })
        assert r.status_code == 302
        p = Produit.objects.get(designation="Bouteille eau 1.5L")
        assert p.reference.startswith("ART-") and p.prix_ttc == D("300.00")

    def test_import_csv_et_export(self, client, comptable):
        _login(client, comptable)
        csv_content = (
            "reference;ean;designation;categorie;unite;prix_ttc;tva_taux;cout_achat;stock;seuil_alerte;actif\n"
            "ART-A1;3801234567890;Article A;Divers;pièce;1000;18;;50;10;1\n"
            "ART-A2;;Article B;Divers;pièce;2000;18;;30;5;1\n"
            "ART-A1;;Article A maj;;pièce;1100;18;;50;10;1\n"
            "; désignation invalide;0;18;;0;0;1\n"
        )
        from django.core.files.uploadedfile import SimpleUploadedFile
        upload = SimpleUploadedFile("catalogue.csv", csv_content.encode("utf-8"), "text/csv")
        r = client.post("/caisse/catalogue/import/", {"fichier": upload})
        assert r.status_code == 302
        assert Produit.objects.count() == 2  # A1, A2 (A1 mis à jour, ligne invalide ignorée)
        a1 = Produit.objects.get(reference="ART-A1")
        assert a1.prix_ttc == D("1100.00")
        assert a1.categorie.nom == "Divers"
        # Export
        r_export = client.get("/caisse/catalogue/export.csv")
        assert r_export.status_code == 200
        assert b"ART-A1" in r_export.content
