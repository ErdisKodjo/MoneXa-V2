"""
Tests services métier du POS — cœur de la valeur (POS-02/04/06/07/08/09/10).
"""
import uuid
import pytest
from decimal import Decimal

from caisse import services
from caisse.models import (
    MoyenPaiement,
    MouvementCaisse,
    MouvementType,
    Produit,
    SessionCaisse,
    SessionStatut,
    Vente,
    VenteStatut,
)
from accounts.models import Notification, Role, User
from finance.models import Payment, PaymentStatus

pytestmark = pytest.mark.django_db

D = Decimal


@pytest.fixture
def gerant(db):
    return User.objects.create_user(
        email="gerantsvc@test.tg", password="Testpass123!", role=Role.GERANT,
    )


@pytest.fixture
def caissier(db):
    return User.objects.create_user(
        email="caissiersvc@test.tg", password="Testpass123!", role=Role.CAISSIER,
    )


@pytest.fixture
def comptable(db):
    return User.objects.create_user(
        email="comptablesvc@test.tg", password="Testpass123!", role=Role.COMPTABLE,
    )


@pytest.fixture
def session(caissier):
    return services.ouvrir_session(caissier, D("5000"))


@pytest.fixture
def produits(db):
    cat = None
    a = Produit.objects.create(
        designation="Sac de riz 50kg", prix_ttc=D("25000"), tva_taux=D("18.00"),
        stock=D("20"), seuil_alerte=D("5"), reference="ART-RIZ01",
    )
    b = Produit.objects.create(
        designation="Huile 5L", prix_ttc=D("5000"), tva_taux=D("18.00"),
        stock=D("2"), seuil_alerte=D("5"), reference="ART-HUILE1",
    )
    return a, b


class TestEnregistrerVente:
    def test_vente_simple_especes_rendu(self, session, caissier, produits):
        riz, _ = produits
        vente, created = services.enregistrer_vente(services.VenteInput(
            session_id=session.pk, vendeur_id=caissier.pk,
            lignes=[services.LigneInput(produit_id=riz.pk, designation=riz.designation,
                                        quantite=D("2"), prix_unitaire_ttc=D("25000"),
                                        tva_taux=D("18"))],
            paiements=[services.PaiementInput(moyen="ESPECES", montant=D("60000"))],
        ))
        assert created is True
        assert vente.total_ttc == D("50000.00")
        assert vente.rendu == D("10000.00")
        # TVA extraite : 50000 / 1.18 = 42372.88 → TVA 7627.12
        assert vente.total_tva == D("7627.12")
        assert vente.total_ht == D("42372.88")

    def test_multi_paiement_mixte_especes_tmoney(self, session, caissier, produits):
        """POS-04 — vente mixte espèces + T-Money soldée et tracée."""
        riz, _ = produits
        vente, _ = services.enregistrer_vente(services.VenteInput(
            session_id=session.pk, vendeur_id=caissier.pk,
            lignes=[services.LigneInput(produit_id=riz.pk, designation=riz.designation,
                                        quantite=D("1"), prix_unitaire_ttc=D("25000"))],
            paiements=[
                services.PaiementInput(moyen="ESPECES", montant=D("10000")),
                services.PaiementInput(moyen="TMONEY", montant=D("15000"),
                                       reference="SBTM-TEST123"),
            ],
        ))
        assert vente.total_ttc == D("25000.00")
        moyens = sorted(p.moyen for p in vente.paiements.all())
        assert moyens == ["ESPECES", "TMONEY"]
        # Espèces nettes : 10000 (pas de rendu)
        mv = vente.mouvements.filter(type=MouvementType.VENTE_ESPECES).first()
        assert mv is not None and mv.montant == D("10000.00")

    def test_stock_decremente_et_alerte_notifiee(self, session, caissier, produits, gerant):
        """POS-09 — décrément stock + notification sous seuil."""
        _, huile = produits  # stock 2, seuil 5 → déjà bas : 1 vente → alerte
        gerant_notifications_avant = Notification.objects.filter(user=gerant).count()
        services.enregistrer_vente(services.VenteInput(
            session_id=session.pk, vendeur_id=caissier.pk,
            lignes=[services.LigneInput(produit_id=huile.pk, designation=huile.designation,
                                        quantite=D("1"), prix_unitaire_ttc=D("5000"))],
            paiements=[services.PaiementInput(moyen="ESPECES", montant=D("5000"))],
        ))
        huile.refresh_from_db()
        assert huile.stock == D("1.00")
        assert Notification.objects.filter(user=gerant).count() > gerant_notifications_avant

    def test_integration_tresorerie_payment_finance(self, session, caissier, produits):
        """POS-08 — chaque moyen crée un Payment natif (journal/KPIs sans double saisie)."""
        riz, _ = produits
        services.enregistrer_vente(services.VenteInput(
            session_id=session.pk, vendeur_id=caissier.pk,
            lignes=[services.LigneInput(produit_id=riz.pk, designation=riz.designation,
                                        quantite=D("1"), prix_unitaire_ttc=D("25000"))],
            paiements=[
                services.PaiementInput(moyen="ESPECES", montant=D("20000")),
                services.PaiementInput(moyen="TMONEY", montant=D("5000")),
            ],
        ))
        vente = Vente.objects.latest("pk")
        refs = list(Payment.objects.filter(provider_ref__startswith=f"POS-{vente.reference}-"))
        assert len(refs) == 2
        assert {p.channel for p in refs} == {"ESPECES", "TMONEY"}
        assert all(p.status == PaymentStatus.RECONCILIE for p in refs)
        # total payé = total TTC (25000)
        assert sum(p.amount for p in refs) == D("25000.00")

    def test_idempotence_replay_sans_doublon(self, session, caissier, produits):
        """POS-10 — replay offline : même clé → même vente, zéro effet de bord."""
        riz, _ = produits
        key = str(uuid.uuid4())
        v1, c1 = services.enregistrer_vente(services.VenteInput(
            session_id=session.pk, vendeur_id=caissier.pk,
            lignes=[services.LigneInput(produit_id=riz.pk, designation=riz.designation,
                                        quantite=D("1"), prix_unitaire_ttc=D("25000"))],
            paiements=[services.PaiementInput(moyen="ESPECES", montant=D("25000"))],
            idempotence_key=key,
        ))
        v2, c2 = services.enregistrer_vente(services.VenteInput(
            session_id=session.pk, vendeur_id=caissier.pk,
            lignes=[services.LigneInput(produit_id=riz.pk, designation=riz.designation,
                                        quantite=D("1"), prix_unitaire_ttc=D("25000"))],
            paiements=[services.PaiementInput(moyen="ESPECES", montant=D("25000"))],
            idempotence_key=key,
        ))
        assert c1 and not c2 and v1.pk == v2.pk
        assert Vente.objects.filter(idempotence_key=key).count() == 1
        riz.refresh_from_db()
        assert riz.stock == D("19.00")  # décrémenté une seule fois

    def test_encaissement_incomplet_refuse(self, session, caissier, produits):
        riz, _ = produits
        with pytest.raises(services.CaisseError):
            services.enregistrer_vente(services.VenteInput(
                session_id=session.pk, vendeur_id=caissier.pk,
                lignes=[services.LigneInput(produit_id=riz.pk, designation=riz.designation,
                                            quantite=D("1"), prix_unitaire_ttc=D("25000"))],
                paiements=[services.PaiementInput(moyen="ESPECES", montant=D("10000"))],
            ))

    def test_panier_vide_refuse(self, session, caissier):
        with pytest.raises(services.CaisseError):
            services.enregistrer_vente(services.VenteInput(
                session_id=session.pk, vendeur_id=caissier.pk,
                lignes=[], paiements=[services.PaiementInput(moyen="ESPECES", montant=D("100"))],
            ))

    def test_remise_panier_et_plafond_role(self, session, caissier):
        """POS-02 — remise OK sous plafond, refusée au-delà."""
        # Caissier : max 5 %
        vente, _ = services.enregistrer_vente(services.VenteInput(
            session_id=session.pk, vendeur_id=caissier.pk,
            lignes=[services.LigneInput(designation="Service", quantite=D("1"),
                                        prix_unitaire_ttc=D("10000"))],
            paiements=[services.PaiementInput(moyen="ESPECES", montant=D("9500"))],
            remise_panier=D("5"),
        ))
        assert vente.total_ttc == D("9500.00")
        with pytest.raises(services.CaisseError):
            services.enregistrer_vente(services.VenteInput(
                session_id=session.pk, vendeur_id=caissier.pk,
                lignes=[services.LigneInput(designation="Service", quantite=D("1"),
                                            prix_unitaire_ttc=D("10000"))],
                paiements=[services.PaiementInput(moyen="ESPECES", montant=D("10000"))],
                remise_panier=D("10"),
            ))

    def test_annulation_restitue_stock_et_neutralise(self, comptable, caissier, produits):
        riz, _ = produits
        s2 = services.ouvrir_session(caissier, D("0"))
        vente, _ = services.enregistrer_vente(services.VenteInput(
            session_id=s2.pk, vendeur_id=caissier.pk,
            lignes=[services.LigneInput(produit_id=riz.pk, designation=riz.designation,
                                        quantite=D("2"), prix_unitaire_ttc=D("25000"))],
            paiements=[services.PaiementInput(moyen="ESPECES", montant=D("50000"))],
        ))
        riz.refresh_from_db()
        assert riz.stock == D("18.00")
        services.annuler_vente(vente, user=comptable)
        riz.refresh_from_db()
        assert riz.stock == D("20.00")  # restitué
        vente.refresh_from_db()
        assert vente.statut == VenteStatut.ANNULEE
        assert Payment.objects.filter(
            provider_ref__startswith=f"POS-{vente.reference}-",
            status=PaymentStatus.ANOMALIE,
        ).count() == 1

    def test_annulation_interdite_au_caissier(self, caissier, produits):
        riz, _ = produits
        s3 = services.ouvrir_session(caissier, D("0"))
        vente, _ = services.enregistrer_vente(services.VenteInput(
            session_id=s3.pk, vendeur_id=caissier.pk,
            lignes=[services.LigneInput(designation="X", quantite=D("1"),
                                        prix_unitaire_ttc=D("1000"))],
            paiements=[services.PaiementInput(moyen="ESPECES", montant=D("1000"))],
        ))
        with pytest.raises(services.CaisseError):
            services.annuler_vente(vente, user=caissier)


class TestSessions:
    def test_rapport_x_et_cloture_z_exacte(self, caissier, produits):
        """POS-06 — clôture exacte au centime sur jeu de test."""
        riz, _ = produits
        session = services.ouvrir_session(caissier, D("10000"))
        # 3 ventes espèces 25000 → cash théorique = 10000 + 75000
        for _ in range(3):
            services.enregistrer_vente(services.VenteInput(
                session_id=session.pk, vendeur_id=caissier.pk,
                lignes=[services.LigneInput(produit_id=riz.pk, designation=riz.designation,
                                            quantite=D("1"), prix_unitaire_ttc=D("25000"))],
                paiements=[services.PaiementInput(moyen="ESPECES", montant=D("25000"))],
            ))
        rapport = services.rapport_session(session)
        assert rapport["nb_tickets"] == 3
        assert rapport["total_ttc"] == D("75000.00")
        assert rapport["especes_theorique"] == D("85000.00")

        services.cloturer_session(session, D("85000"), note="Comptage exact")
        session.refresh_from_db()
        assert session.statut == SessionStatut.FERMEE
        assert session.ecart == D("0.00")

    def test_ecart_signale_anomalie_audit_notification(self, caissier, gerant, produits):
        """POS-07 — écart > tolérance → notification gérant + audit immuable."""
        riz, _ = produits
        session = services.ouvrir_session(caissier, D("10000"))
        services.enregistrer_vente(services.VenteInput(
            session_id=session.pk, vendeur_id=caissier.pk,
            lignes=[services.LigneInput(produit_id=riz.pk, designation=riz.designation,
                                        quantite=D("1"), prix_unitaire_ttc=D("25000"))],
            paiements=[services.PaiementInput(moyen="ESPECES", montant=D("25000"))],
        ))
        # Théorique 35000 ; comptage 34000 → écart -1000 (> 500 tolérance)
        services.cloturer_session(session, D("34000"))
        session.refresh_from_db()
        assert session.ecart == D("-1000.00")
        notifs = Notification.objects.filter(user=gerant, kind="ANOMALIE")
        assert notifs.exists()
        assert "écart" in notifs.first().title.lower()
        # Audit immuable
        from auditing.models import AuditLog
        assert AuditLog.objects.filter(
            action="CAISSE_ECART_FLAGGED", entity_id=str(session.pk)
        ).exists()

    def test_ecart_dans_tolerance_pas_d_anomalie(self, caissier, gerant, db):
        session = services.ouvrir_session(caissier, D("10000"))
        services.cloturer_session(session, D("9970"))  # écart -30 ≤ 500
        assert not Notification.objects.filter(user=gerant, kind="ANOMALIE").exists()

    def test_mouvement_depot_reduit_especes_theorique(self, caissier):
        session = services.ouvrir_session(caissier, D("20000"))
        MouvementCaisse.objects.create(
            session=session, type=MouvementType.DEPOT, montant=D("-5000"),
            note="Dépôt de sécurisation", created_by=caissier,
        )
        assert services.total_especes_theorique(session) == D("15000.00")

    def test_cloture_double_refusee(self, caissier):
        session = services.ouvrir_session(caissier, D("0"))
        services.cloturer_session(session, D("0"))
        with pytest.raises(services.CaisseError):
            services.cloturer_session(session, D("0"))

    def test_deuxieme_ouverture_refusee(self, caissier):
        services.ouvrir_session(caissier, D("1000"))
        with pytest.raises(services.CaisseError):
            services.ouvrir_session(caissier, D("1000"))
