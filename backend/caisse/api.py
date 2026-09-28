"""
API REST du module caisse (POS) — consommation par l'app mobile Flutter.

Routes (préfixe /api/caisse/, JWT obligatoire) :
- GET  /api/caisse/produits/          — catalogue actif (?q= recherche, ?categorie=)
- GET  /api/caisse/session/           — session ouverte de l'utilisateur + rapport X
- POST /api/caisse/session/           — ouverture (fond de caisse)
- POST /api/caisse/session/cloture/   — clôture Z (comptage physique, note)
- GET  /api/caisse/ventes/            — historique (caissier : les siennes,
                                        comptable+ : toutes ; ?statut=&q=)
- POST /api/caisse/ventes/            — vente idempotente (POS-10) réutilisant
                                        services.enregistrer_vente (une seule
                                        source de vérité : web et mobile)

RBAC aligné sur le WebUI : vendre = Caissier+ ; chaque vendeur ne voit que
ses sessions/ventes, Comptable+ voit tout. Les erreurs métier CaisseError
sont renvoyées en 400 avec un message exploitable par l'app.
"""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Q
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from accounts.permissions import IsCaissierOrHigher, IsComptableOrHigher
from auditing.services import log_action
from . import services
from .models import (
    Produit,
    SessionCaisse,
    SessionStatut,
    Vente,
    VenteStatut,
)
from .serializers import (
    ClotureSerializer,
    OuvertureSerializer,
    ProduitSerializer,
    SessionCaisseSerializer,
    VenteCreateSerializer,
    VenteSerializer,
)


def _rapport_payload(session: SessionCaisse) -> dict:
    """Rapport X aplati pour l'app mobile (Décimals en string)."""
    rapport = services.rapport_session(session)
    return {
        "nb_tickets": rapport["nb_tickets"],
        "total_ht": str(rapport["total_ht"]),
        "total_tva": str(rapport["total_tva"]),
        "total_ttc": str(rapport["total_ttc"]),
        "panier_moyen": str(rapport["panier_moyen"]),
        "especes_theorique": str(rapport["especes_theorique"]),
        "fond_caisse": str(rapport["fond_caisse"]),
        "par_moyen": [
            {
                "moyen": moyen,
                "label": entry["label"],
                "montant": str(entry["montant"]),
                "nb": entry["nb"],
            }
            for moyen, entry in rapport["par_moyen"].items()
        ],
    }


class CaisseProduitsView(APIView):
    """GET /api/caisse/produits/ — catalogue actif, recherche EAN/désignation/réf."""

    permission_classes = [IsCaissierOrHigher]

    def get(self, request):
        qs = Produit.objects.filter(actif=True).select_related("categorie")
        q = (request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(designation__icontains=q)
                | Q(reference__icontains=q)
                | Q(ean=q)
            )
        categorie = (request.query_params.get("categorie") or "").strip()
        if categorie:
            qs = qs.filter(categorie_id=categorie)
        serializer = ProduitSerializer(qs[:500], many=True)
        return Response(serializer.data)


class CaisseSessionView(APIView):
    """
    GET  /api/caisse/session/  — session ouverte du vendeur courant (+ rapport X).
    POST /api/caisse/session/  — ouverture {fond_caisse}.
    """

    permission_classes = [IsCaissierOrHigher]

    def get(self, request):
        session = SessionCaisse.objects.filter(
            vendeur=request.user, statut=SessionStatut.OUVERTE
        ).first()
        if session is None:
            return Response({"session": None, "rapport": None})
        return Response(
            {
                "session": SessionCaisseSerializer(session).data,
                "rapport": _rapport_payload(session),
            }
        )

    def post(self, request):
        serializer = OuvertureSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            session = services.ouvrir_session(
                request.user, serializer.validated_data["fond_caisse"],
                ip=request.META.get("REMOTE_ADDR"),
            )
        except services.CaisseError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            SessionCaisseSerializer(session).data, status=status.HTTP_201_CREATED
        )


class CaisseClotureView(APIView):
    """POST /api/caisse/session/cloture/ — rapport Z + écart + anomalies auto."""

    permission_classes = [IsCaissierOrHigher]

    def post(self, request):
        serializer = ClotureSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = SessionCaisse.objects.filter(
            vendeur=request.user, statut=SessionStatut.OUVERTE
        ).first()
        if session is None:
            return Response(
                {"detail": "Aucune session ouverte à clôturer."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            fermee = services.cloturer_session(
                session,
                comptage_physique=serializer.validated_data["comptage_physique"],
                note=serializer.validated_data.get("note", ""),
                ip=request.META.get("REMOTE_ADDR"),
            )
        except services.CaisseError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(SessionCaisseSerializer(fermee).data)


class CaisseVentesView(APIView):
    """
    GET  /api/caisse/ventes/ — historique scopé par rôle (?statut=&q=).
    POST /api/caisse/ventes/ — vente idempotente sur la session ouverte.
    """

    permission_classes = [IsCaissierOrHigher]

    def get(self, request):
        qs = Vente.objects.select_related("vendeur", "session").prefetch_related(
            "lignes", "paiements"
        )
        if not request.user.is_comptable_or_higher():
            qs = qs.filter(vendeur=request.user)
        statut = (request.query_params.get("statut") or "").strip()
        if statut and statut in VenteStatut.values:
            qs = qs.filter(statut=statut)
        q = (request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(reference__icontains=q)
                | Q(client_name__icontains=q)
                | Q(client_phone__icontains=q)
            )
        serializer = VenteSerializer(qs[:200], many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = VenteCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        session = SessionCaisse.objects.filter(
            vendeur=request.user, statut=SessionStatut.OUVERTE
        ).first()
        if session is None:
            return Response(
                {"detail": "Ouvrez une session de caisse avant d'encaisser."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        lignes_input = []
        for ligne in data["lignes"]:
            produit = Produit.objects.filter(
                pk=ligne["produit_id"], actif=True
            ).first()
            if produit is None:
                return Response(
                    {"detail": f"Produit #{ligne['produit_id']} introuvable ou inactif."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            lignes_input.append(
                services.LigneInput(
                    produit_id=produit.pk,
                    designation=produit.designation,
                    quantite=ligne["quantite"],
                    prix_unitaire_ttc=produit.prix_ttc,
                    tva_taux=produit.tva_taux,
                    remise_pct=ligne.get("remise_pct", Decimal("0")),
                )
            )
        paiements_input = [
            services.PaiementInput(
                moyen=p["moyen"], montant=p["montant"], reference=p.get("reference", "")
            )
            for p in data["paiements"]
        ]
        vente_input = services.VenteInput(
            session_id=session.pk,
            vendeur_id=request.user.pk,
            lignes=lignes_input,
            paiements=paiements_input,
            remise_panier=data.get("remise_panier_pct", Decimal("0")),
            client_name=data.get("client_name", ""),
            client_phone=data.get("client_phone", ""),
            idempotence_key=data.get("idempotence_key") or None,
        )
        try:
            vente, created = services.enregistrer_vente(
                vente_input, ip=request.META.get("REMOTE_ADDR")
            )
        except services.CaisseError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception:
            return Response(
                {"detail": "Encaissement impossible — réessayez."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        payload = VenteSerializer(vente).data
        payload["created"] = created
        return Response(
            payload,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )
