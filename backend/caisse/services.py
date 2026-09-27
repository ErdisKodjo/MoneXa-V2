"""
Services métier du POS — cahier des charges entreprise v3.0 §5.

Points d'entrée :
- enregistrer_vente()      : vente atomique → lignes + paiements + stock +
                             trésorerie + session + audit (POS-02/04/08/09/10)
- ouvrir_session()         : fond de caisse (POS-06)
- cloturer_session()       : rapport Z, écart espèces, anomalie auto (POS-07)
- rapport_session()        : détail par moyen (X à chaud, Z figé)
- remise_autorisee()       : plafonds de remise par rôle (POS-02)

Toutes les écritures sont idempotentes : la clé d'idempotence de la vente
garantit qu'un replay (réseau instable, file offline) ne duplique rien.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Optional

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from accounts.models import Notification, Role, User
from auditing.services import log_action
from finance.models import Channel, Payment, PaymentStatus, MatchMethod
from .models import (
    LigneVente,
    MoyenPaiement,
    MouvementCaisse,
    MouvementType,
    PaiementVente,
    Produit,
    SessionCaisse,
    SessionStatut,
    Vente,
    VenteStatut,
)

CENT = Decimal("0.01")
Q2 = lambda v: Decimal(v).quantize(CENT, rounding=ROUND_HALF_UP)  # noqa: E731

# Canal de trésorerie finance par moyen POS (CARTE → BANQUE, terminal externe)
CANAL_PAR_MOYEN = {
    MoyenPaiement.ESPECES: Channel.ESPECES,
    MoyenPaiement.TMONEY: Channel.TMONEY,
    MoyenPaiement.MOOV: Channel.MOOV,
    MoyenPaiement.FLOOZ: Channel.FLOOZ,
    MoyenPaiement.CARTE: Channel.BANQUE,
}


class CaisseError(Exception):
    """Erreur métier du POS — message destiné au vendeur."""


# ──────────────────────────────────────────────────────────────────────────
# Remises — plafonds par rôle (POS-02)
# ──────────────────────────────────────────────────────────────────────────
def plafond_remise_pct(user: User) -> Decimal:
    """Remise ligne/panier maximale autorisée (%) selon le rôle."""
    if user.is_comptable_or_higher():
        return Q2(getattr(settings, "CAISSE_REMISE_MAX_COMPTABLE", "25.00"))
    return Q2(getattr(settings, "CAISSE_REMISE_MAX_CAISSIER", "5.00"))


def verifier_remise(user: User, remise_pct: Decimal) -> None:
    """Lève CaisseError si la remise dépasse le plafond du rôle."""
    plafond = plafond_remise_pct(user)
    if remise_pct > plafond:
        raise CaisseError(
            f"Remise de {remise_pct} % refusée : votre rôle autorise au maximum "
            f"{plafond} % (au-delà, sollicitez un comptable ou le gérant)."
        )


# ──────────────────────────────────────────────────────────────────────────
# Dataclasses d'entrée
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class LigneInput:
    produit_id: Optional[int] = None
    designation: str = ""
    quantite: Decimal = Decimal("1")
    prix_unitaire_ttc: Decimal = Decimal("0")
    tva_taux: Decimal = Decimal("18.00")
    remise_pct: Decimal = Decimal("0")


@dataclass
class PaiementInput:
    moyen: str
    montant: Decimal
    reference: str = ""  # n° opérateur (repli manuel mobile money)


@dataclass
class VenteInput:
    session_id: int
    vendeur_id: int
    lignes: list[LigneInput] = field(default_factory=list)
    paiements: list[PaiementInput] = field(default_factory=list)
    remise_panier: Decimal = Decimal("0")
    client_name: str = ""
    client_phone: str = ""
    idempotence_key: Optional[str] = None
    note: str = ""


# ──────────────────────────────────────────────────────────────────────────
# Sessions de caisse (POS-06)
# ──────────────────────────────────────────────────────────────────────────
def ouvrir_session(vendeur: User, fond_caisse: Decimal, *, ip: str | None = None) -> SessionCaisse:
    """Ouvre une session avec fond de caisse déclaré (une seule ouverte/vendeur)."""
    if SessionCaisse.objects.filter(vendeur=vendeur, statut=SessionStatut.OUVERTE).exists():
        raise CaisseError("Vous avez déjà une session de caisse ouverte.")
    session = SessionCaisse.objects.create(
        vendeur=vendeur, fond_caisse=Q2(fond_caisse),
    )
    log_action(
        user=vendeur, action="CAISSE_SESSION_OPENED", entity="SessionCaisse",
        entity_id=str(session.pk), details={"fond_caisse": str(session.fond_caisse)},
        ip_address=ip,
    )
    return session


def total_especes_theorique(session: SessionCaisse) -> Decimal:
    """
    Espèces théoriques en caisse = fond de caisse
    + ventes espèces (net du rendu) − sorties (dépôts, retraits, dépenses).
    """
    total = session.fond_caisse
    for m in session.mouvements.all():
        total += m.montant
    return Q2(total)


def rapport_session(session: SessionCaisse) -> dict:
    """
    Détail par moyen de paiement + mouvements d'espèces (rapport X à chaud,
    base du rapport Z figé à la clôture).
    """
    ventes = session.ventes.filter(statut=VenteStatut.VALIDEE)
    par_moyen: dict[str, dict] = {}
    total_ttc = Decimal("0")
    total_tva = Decimal("0")
    total_ht = Decimal("0")
    nb_tickets = 0
    for v in ventes:
        nb_tickets += 1
        total_ttc += v.total_ttc
        total_tva += v.total_tva
        total_ht += v.total_ht
        for p in v.paiements.all():
            entry = par_moyen.setdefault(
                p.moyen, {"montant": Decimal("0"), "nb": 0, "label": p.get_moyen_display()},
            )
            entry["montant"] += p.montant
            entry["nb"] += 1
    especes_theorique = total_especes_theorique(session)
    return {
        "par_moyen": par_moyen,
        "nb_tickets": nb_tickets,
        "total_ttc": Q2(total_ttc),
        "total_tva": Q2(total_tva),
        "total_ht": Q2(total_ht),
        "panier_moyen": Q2(total_ttc / nb_tickets) if nb_tickets else Decimal("0"),
        "especes_theorique": especes_theorique,
        "fond_caisse": session.fond_caisse,
        "mouvements": list(session.mouvements.all()),
    }


def cloturer_session(
    session: SessionCaisse,
    comptage_physique: Decimal,
    *,
    note: str = "",
    ip: str | None = None,
) -> SessionCaisse:
    """
    Clôture Z : détail par moyen, comptage physique saisi, écart calculé.
    Un écart au-delà du seuil de tolérance crée automatiquement une
    notification d'anomalie vers les gérants + entrée d'audit immuable (POS-07).
    """
    if session.statut == SessionStatut.FERMEE:
        raise CaisseError("Session déjà clôturée.")
    comptage_physique = Q2(comptage_physique)
    especes_theorique = total_especes_theorique(session)
    ecart = Q2(comptage_physique - especes_theorique)

    with transaction.atomic():
        session.statut = SessionStatut.FERMEE
        session.fermee_at = timezone.now()
        session.comptage_physique = comptage_physique
        session.ecart = ecart
        session.note = note
        session.save()

        # Mouvement d'écart tracé dans la session (lecture claire du rapport)
        if ecart != Decimal("0"):
            MouvementCaisse.objects.create(
                session=session, type=MouvementType.ECART, montant=ecart,
                note=f"Écart constaté à la clôture (théorique {especes_theorique} FCFA)",
                created_by=session.vendeur,
            )

        rapport = rapport_session(session)
        log_action(
            user=session.vendeur, action="CAISSE_SESSION_CLOSED", entity="SessionCaisse",
            entity_id=str(session.pk),
            details={
                "total_ttc": str(rapport["total_ttc"]),
                "especes_theorique": str(especes_theorique),
                "comptage_physique": str(comptage_physique),
                "ecart": str(ecart),
            },
            ip_address=ip,
        )

        # Contrôle anti-fraude (POS-07) — écart hors tolérance → anomalie
        seuil = Q2(getattr(settings, "CAISSE_ECART_TOLERANCE", "500.00"))
        if abs(ecart) > seuil:
            flag_ecart_anomalie(session, ecart, especes_theorique, comptage_physique)

    return session


def flag_ecart_anomalie(
    session: SessionCaisse, ecart: Decimal, theorique: Decimal, physique: Decimal
) -> None:
    """
    Anomalie d'écart de caisse : notification prioritaire aux gérants +
    entrée audit immuable. Consommée sur la page Anomalies (vue étendue).
    """
    direction = "manquant" if ecart < 0 else "excédentaire"
    title = (
        f"Écart de caisse {direction} de {abs(ecart):,.2f} FCFA "
        f"— {session.vendeur.display_name} (session #{session.pk})"
    )
    body = (
        f"Clôture de la session #{session.pk} de {session.vendeur.display_name} : "
        f"théorique {theorique:,.2f} FCFA, comptage physique {physique:,.2f} FCFA, "
        f"écart {ecart:,.2f} FCFA (tolérance "
        f"{getattr(settings, 'CAISSE_ECART_TOLERANCE', '500.00')} FCFA). "
        f"Contrôle requis."
    )
    for gerant in User.objects.filter(role=Role.GERANT, is_active=True):
        Notification.objects.create(
            user=gerant, kind="ANOMALIE", title=title, body=body, url="/anomalies/",
        )
    log_action(
        user=session.vendeur, action="CAISSE_ECART_FLAGGED", entity="SessionCaisse",
        entity_id=str(session.pk),
        details={"ecart": str(ecart), "theorique": str(theorique), "physique": str(physique)},
    )


# ──────────────────────────────────────────────────────────────────────────
# Vente (POS-02 / POS-04 / POS-08 / POS-09 / POS-10)
# ──────────────────────────────────────────────────────────────────────────
def _montant_ligne(ligne: LigneInput) -> Decimal:
    brut = ligne.quantite * ligne.prix_unitaire_ttc
    remise = brut * ligne.remise_pct / Decimal("100")
    return Q2(brut - remise)


def enregistrer_vente(
    data: VenteInput, *, ip: str | None = None
) -> tuple[Vente, bool]:
    """
    Enregistre une vente de façon atomique et idempotente.

    Retourne (vente, created). Si la clé d'idempotence a déjà été traitée,
    la vente existante est renvoyée sans effet de bord (POS-10).

    Effets (POS-08 / POS-09) :
    - LigneVente snapshot + totaux TVA/HT/TTC
    - PaiementVente par moyen (rendu espèces calculé)
    - Stock décrémenté, alerte seuil → notification gérants
    - finance.Payment natif par moyen → journal, KPIs, exports cohérents
    - Mouvement d'espèces net dans la session
    - Audit immuable POS_SALE_CREATED
    """
    # Idempotence : replay offline → retour de la vente déjà créée
    if data.idempotence_key:
        existing = Vente.objects.filter(idempotence_key=data.idempotence_key).first()
        if existing:
            return existing, False
        key = str(data.idempotence_key)
    else:
        key = str(uuid.uuid4())

    with transaction.atomic():
        session = SessionCaisse.objects.select_for_update().get(pk=data.session_id)
        if session.statut != SessionStatut.OUVERTE:
            raise CaisseError("La session de caisse n'est pas ouverte.")
        vendeur = User.objects.get(pk=data.vendeur_id)
        if session.vendeur_id != vendeur.id and not vendeur.is_comptable_or_higher():
            raise CaisseError("Seul le titulaire de la session (ou un comptable+) peut encaisser.")
        if not data.lignes:
            raise CaisseError("Le panier est vide.")

        # Plafonds de remise par rôle (POS-02)
        verifier_remise(vendeur, Q2(data.remise_panier))
        for ligne in data.lignes:
            verifier_remise(vendeur, Q2(ligne.remise_pct))
            if ligne.remise_pct < 0 or ligne.quantite <= 0:
                raise CaisseError("Quantités et remises doivent être positives.")

        # Totaux : TTC lignes × (1 − remise panier %), TVA extraite au prorata
        brut_lignes = sum((_montant_ligne(l) for l in data.lignes), Decimal("0"))
        remise_valeur = Q2(brut_lignes * Q2(data.remise_panier) / Decimal("100"))
        total_ttc = Q2(brut_lignes - remise_valeur)
        if total_ttc < 0:
            raise CaisseError("La remise panier ne peut pas dépasser le total du panier.")

        # Multi-paiement (POS-04) : somme >= TTC, rendu sur la part espèces
        total_paye = sum((Q2(p.montant) for p in data.paiements), Decimal("0"))
        if total_paye < total_ttc:
            raise CaisseError(
                f"Encaissement incomplet : reçu {total_paye:,.2f} FCFA "
                f"pour un total de {total_ttc:,.2f} FCFA."
            )
        especes_payees = sum(
            (Q2(p.montant) for p in data.paiements if p.moyen == MoyenPaiement.ESPECES),
            Decimal("0"),
        )
        rendu = Q2(min(especes_payees, total_paye - total_ttc))
        for p in data.paiements:
            if Q2(p.montant) <= 0:
                raise CaisseError("Chaque paiement doit être strictement positif.")
            if p.moyen not in MoyenPaiement.values:
                raise CaisseError(f"Moyen de paiement inconnu : {p.moyen}")

        vente = Vente.objects.create(
            reference=Vente.generate_reference(),
            idempotence_key=key,
            session=session,
            vendeur=vendeur,
            client_name=data.client_name.strip(),
            client_phone=data.client_phone.strip(),
            total_ttc=total_ttc,
            remise_panier=Q2(data.remise_panier),
            rendu=rendu,
        )

        # Lignes + stock (POS-09)
        for ligne in data.lignes:
            total_ligne = _montant_ligne(ligne)
            produit = None
            if ligne.produit_id:
                produit = Produit.objects.select_for_update().filter(pk=ligne.produit_id).first()
            LigneVente.objects.create(
                vente=vente,
                produit=produit,
                designation=(produit.designation if produit else ligne.designation)[:200],
                quantite=Q2(ligne.quantite),
                prix_unitaire_ttc=Q2(ligne.prix_unitaire_ttc),
                tva_taux=Q2(ligne.tva_taux),
                remise_pct=Q2(ligne.remise_pct),
                total_ttc=total_ligne,
            )
            if produit:
                produit.stock = Q2(produit.stock - ligne.quantite)
                produit.save(update_fields=["stock", "updated_at"])
                if produit.stock_bas:
                    notifier_stock_bas(produit)

        # Recalcul TVA/HT exacts au prorata des lignes réelles
        total_tva = sum((l.total_tva for l in vente.lignes.all()), Decimal("0"))
        total_tva = Q2(total_tva * (total_ttc / brut_lignes)) if brut_lignes > 0 else Decimal("0")
        vente.total_tva = total_tva
        vente.total_ht = Q2(total_ttc - total_tva)
        vente.save(update_fields=["total_tva", "total_ht"])

        # Paiements + intégration trésorerie (POS-08)
        for p in data.paiements:
            PaiementVente.objects.create(
                vente=vente, moyen=p.moyen, montant=Q2(p.montant), reference=p.reference,
            )
            _creer_mouvement_tresorerie(vente, p)

        # Espèces nettes → mouvement de session (POS-06)
        especes_net = Q2(especes_payees - rendu)
        if especes_net > 0:
            MouvementCaisse.objects.create(
                session=session, type=MouvementType.VENTE_ESPECES,
                montant=especes_net, vente=vente, created_by=vendeur,
            )

        log_action(
            user=vendeur, action="POS_SALE_CREATED", entity="Vente",
            entity_id=vente.reference,
            details={
                "total_ttc": str(total_ttc), "nb_lignes": len(data.lignes),
                "moyens": [p.moyen for p in data.paiements], "rendu": str(rendu),
            },
            ip_address=ip,
        )
        return vente, True


def _creer_mouvement_tresorerie(vente: Vente, paiement: PaiementInput) -> None:
    """
    Intégration native (§5.5) : le paiement de vente devient un Payment
    finance (journal de caisse, KPIs, exports PDF) — sans double saisie.
    provider_ref « POS-<ref>-<moyen> » unique = anti-doublon DB.
    """
    Payment.objects.get_or_create(
        provider_ref=f"POS-{vente.reference}-{paiement.moyen}",
        defaults={
            "amount": Q2(paiement.montant),
            "channel": CANAL_PAR_MOYEN[paiement.moyen],
            "payer_name": vente.client_name or "Client comptoir",
            "payer_phone": vente.client_phone,
            "paid_at": vente.created_at,
            "status": PaymentStatus.RECONCILIE,
            "match_method": MatchMethod.MANUEL,
            "raw_text": f"Vente POS {vente.reference} — encaissement direct "
                        f"({paiement.reference or 'sans référence opérateur'})",
            "ai_confidence": 1.0,
            "created_by": vente.vendeur,
        },
    )


def notifier_stock_bas(produit: Produit) -> None:
    """Alerte de réapprovisionnement aux gérants + comptables (POS-09)."""
    title = f"Stock bas : {produit.designation} ({produit.reference})"
    body = (
        f"Stock restant {produit.stock:,.2f} {produit.unite}(s) — "
        f"seuil d'alerte {produit.seuil_alerte:,.2f}. Réapprovisionnement conseillé."
    )
    for u in User.objects.filter(
        role__in=[Role.GERANT, Role.COMPTABLE], is_active=True
    ):
        Notification.objects.get_or_create(
            user=u, kind="INFO", title=title,
            defaults={"body": body, "url": "/caisse/catalogue/"},
        )


def annuler_vente(vente: Vente, *, user: User, ip: str | None = None) -> Vente:
    """
    Annulation d'une vente (comptable+ uniquement) : statut ANNULEE,
    stock restitué, mouvement espèces inversé, payment finance neutralisé
    via statut ANOMALIE (tracé, jamais supprimé — chaîne d'audit intacte).
    """
    if user and not user.is_comptable_or_higher():
        raise CaisseError("Seul un comptable ou le gérant peut annuler une vente.")
    if vente.statut == VenteStatut.ANNULEE:
        return vente
    with transaction.atomic():
        vente.statut = VenteStatut.ANNULEE
        vente.save(update_fields=["statut"])
        # Restitution du stock
        for ligne in vente.lignes.select_related("produit"):
            if ligne.produit_id and ligne.produit:
                ligne.produit.stock = Q2(ligne.produit.stock + ligne.quantite)
                ligne.produit.save(update_fields=["stock", "updated_at"])
        # Inverse du mouvement d'espèces de session
        for m in vente.mouvements.filter(type=MouvementType.VENTE_ESPECES):
            MouvementCaisse.objects.create(
                session=m.session, type=MouvementType.RETRAIT,
                montant=-m.montant, note=f"Annulation vente {vente.reference}",
                created_by=user,
            )
        # Neutralisation des payments finance (traçabilité, zéro suppression)
        Payment.objects.filter(provider_ref__startswith=f"POS-{vente.reference}-").update(
            status=PaymentStatus.ANOMALIE
        )
        log_action(
            user=user, action="POS_SALE_CANCELLED", entity="Vente",
            entity_id=vente.reference, details={"total_ttc": str(vente.total_ttc)},
            ip_address=ip,
        )
    return vente
