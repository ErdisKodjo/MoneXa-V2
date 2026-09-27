"""
Vues WebUI du module caisse (POS) — cahier des charges entreprise v3.0 §5.

Routes (préfixe /caisse/, noms préfixés caisse_) :
- /caisse/                         — terminal de vente tactile (Caissier+)
- /caisse/session/                 — ouverture, rapport X, clôture Z (POS-06/07)
- /caisse/ventes/                  — historique des ventes
- /caisse/ventes/<ref>/ticket.pdf  — ticket PDF 58 mm
- /caisse/ventes/<ref>/ticket.escpos — flux binaire ESC/POS (imprimante)
- /caisse/catalogue/               — gestion produits (Comptable+, POS-01)
- /caisse/catalogue/import|export  — CSV référentiel
- /caisse/ventes/<ref>/annuler/    — annulation (Comptable+)

RBAC : vendre = Caissier+ ; catalogue/annulations = Comptable+ ; chaque
vendeur ne voit que ses sessions/ventes, Comptable+ voit tout.
"""
from __future__ import annotations

import csv
import io
import json
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.http import (
    FileResponse,
    Http404,
    HttpResponse,
    HttpResponseBadRequest,
)
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic import ListView, TemplateView, View

from accounts.models import User
from webui.mixins import CaissierRequiredMixin, ComptableRequiredMixin
from . import services
from .forms import (
    CategorieForm,
    CloturerSessionForm,
    MouvementCaisseForm,
    OuvrirSessionForm,
    ProduitForm,
)
from .models import (
    Categorie,
    MoyenPaiement,
    Produit,
    SessionCaisse,
    SessionStatut,
    Vente,
    VenteStatut,
)
from .tickets import ticket_escpos_bytes, ticket_pdf, ticket_texte


def _session_ouverte(user: User) -> SessionCaisse | None:
    return SessionCaisse.objects.filter(vendeur=user, statut=SessionStatut.OUVERTE).first()


# ═══════════════════════════════════════════════════════════════════════════
# Terminal de vente (POS-02 / POS-04)
# ═══════════════════════════════════════════════════════════════════════════
class POSTerminalView(CaissierRequiredMixin, TemplateView):
    """Écran d'encaissement comptoir : catalogue tactile + panier + multi-paiement."""

    template_name = "caisse/pos.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        session = _session_ouverte(self.request.user)
        ctx["session"] = session
        ctx["produits"] = Produit.objects.filter(actif=True).select_related("categorie")
        ctx["categories"] = {p.categorie for p in ctx["produits"] if p.categorie}
        ctx["moyens"] = MoyenPaiement.choices
        ctx["plafond_remise"] = services.plafond_remise_pct(self.request.user)
        ctx["ecart_tolerance"] = getattr(_settings(), "CAISSE_ECART_TOLERANCE", "500.00")
        if session:
            ctx["rapport"] = services.rapport_session(session)
        # Dernière vente encaissée (confirmation avec accès ticket)
        last_id = self.request.session.pop("caisse_last_vente_id", None)
        if last_id:
            ctx["derniere_vente"] = Vente.objects.filter(pk=last_id).first()
        return ctx

    def post(self, request, *args, **kwargs):
        """Encaissement : panier JSON (`cart`) ou vente rapide (`quick=1`)."""
        session = _session_ouverte(request.user)
        if not session:
            messages.error(
                request, _("Ouvrez une session de caisse avant d'encaisser.")
            )
            return redirect("caisse_pos")

        # Vente rapide : montant libre (service), payé en espèces — accessible
        # même sans JavaScript (mode dégradé du terminal).
        if request.POST.get("quick") == "1":
            try:
                montant = _dec(request.POST.get("quick_amount", "0"))
                if montant <= 0:
                    raise ValueError
            except (ValueError, InvalidOperation):
                messages.error(request, _("Montant de vente rapide invalide."))
                return redirect("caisse_pos")
            try:
                vente, created = services.enregistrer_vente(
                    services.VenteInput(
                        session_id=session.pk,
                        vendeur_id=request.user.pk,
                        lignes=[services.LigneInput(
                            designation="Vente rapide", quantite=Decimal("1"),
                            prix_unitaire_ttc=montant, tva_taux=Decimal("18"),
                        )],
                        paiements=[services.PaiementInput(moyen="ESPECES", montant=montant)],
                    ),
                    ip=request.META.get("REMOTE_ADDR"),
                )
            except (services.CaisseError, ValueError) as exc:
                messages.error(request, str(exc))
                return redirect("caisse_pos")
            messages.success(
                request,
                _(f"Vente rapide {vente.reference} encaissée — {vente.total_ttc:,.2f} FCFA."),
            )
            request.session["caisse_last_vente_id"] = vente.pk
            return redirect("caisse_pos")

        try:
            cart = json.loads(request.POST.get("cart", "{}"))
        except json.JSONDecodeError:
            return HttpResponseBadRequest("Panier invalide.")

        try:
            lignes = [
                services.LigneInput(
                    produit_id=int(l["produit_id"]) if l.get("produit_id") else None,
                    designation=str(l.get("designation", "Article")),
                    quantite=_dec(l.get("quantite", 1)),
                    prix_unitaire_ttc=_dec(l.get("prix_unitaire_ttc", 0)),
                    tva_taux=_dec(l.get("tva_taux", 18)),
                    remise_pct=_dec(l.get("remise_pct", 0)),
                )
                for l in cart.get("lignes", [])
            ]
            paiements = [
                services.PaiementInput(
                    moyen=str(p.get("moyen", "ESPECES")),
                    montant=_dec(p.get("montant", 0)),
                    reference=str(p.get("reference", ""))[:60],
                )
                for p in cart.get("paiements", [])
            ]
            vente, created = services.enregistrer_vente(
                services.VenteInput(
                    session_id=session.pk,
                    vendeur_id=request.user.pk,
                    lignes=lignes,
                    paiements=paiements,
                    remise_panier=_dec(cart.get("remise_panier", 0)),
                    client_name=str(cart.get("client_name", ""))[:200],
                    client_phone=str(cart.get("client_phone", ""))[:20],
                    idempotence_key=cart.get("idempotence_key") or None,
                ),
                ip=request.META.get("REMOTE_ADDR"),
            )
        except (services.CaisseError, ValueError, InvalidOperation) as exc:
            messages.error(request, str(exc))
            return redirect("caisse_pos")
        except KeyError as exc:
            messages.error(request, _(f"Données de panier incomplètes : {exc}"))
            return redirect("caisse_pos")

        if not created:
            messages.info(
                request,
                _(f"Vente {vente.reference} déjà enregistrée (rejouée sans doublon)."),
            )
        else:
            messages.success(
                request,
                _(f"Vente {vente.reference} encaissée — {vente.total_ttc:,.2f} FCFA."),
            )
        request.session["caisse_last_vente_id"] = vente.pk
        return redirect("caisse_pos")


def _dec(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _settings():
    from django.conf import settings as s
    return s


# ═══════════════════════════════════════════════════════════════════════════
# Session de caisse — ouverture, X, Z (POS-06 / POS-07)
# ═══════════════════════════════════════════════════════════════════════════
class CaisseSessionView(CaissierRequiredMixin, TemplateView):
    """Rapport X à chaud, mouvements, clôture Z avec contrôle d'écart."""

    template_name = "caisse/session.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        session = _session_ouverte(user)
        ctx["session"] = session
        ctx["form_ouvrir"] = OuvrirSessionForm()
        ctx["form_mouvement"] = MouvementCaisseForm()
        ctx["form_cloture"] = CloturerSessionForm()
        if session:
            ctx["rapport"] = services.rapport_session(session)
        # Historique : ses sessions (ou toutes pour Comptable+)
        qs = SessionCaisse.objects.select_related("vendeur")
        ctx["sessions"] = (qs if user.is_comptable_or_higher() else qs.filter(vendeur=user))[:20]
        return ctx

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action", "")

        if action == "ouvrir":
            form = OuvrirSessionForm(request.POST)
            if form.is_valid():
                try:
                    session = services.ouvrir_session(
                        request.user, form.cleaned_data["fond_caisse"],
                        ip=request.META.get("REMOTE_ADDR"),
                    )
                    messages.success(
                        request,
                        _("Session #%(pk)s ouverte — fond de caisse "
                          "%(fond)s FCFA.") % {"pk": session.pk, "fond": f"{session.fond_caisse:,.2f}"},
                    )
                except services.CaisseError as exc:
                    messages.error(request, str(exc))
            else:
                messages.error(request, _("Fond de caisse invalide."))
            return redirect("caisse_session")

        session = _session_ouverte(request.user)
        if not session:
            messages.error(request, _("Aucune session ouverte."))
            return redirect("caisse_session")

        if action == "mouvement":
            form = MouvementCaisseForm(request.POST)
            if form.is_valid():
                from .models import MouvementCaisse

                mtype = form.cleaned_data["type"]
                montant = form.cleaned_data["montant"]
                # Dépôt de sécurisation, retrait, dépense : tous des sorties d'espèces
                # disponibles à la vente → signe négatif dans le théorique
                signe = Decimal("-1")
                MouvementCaisse.objects.create(
                    session=session, type=mtype, montant=signe * montant,
                    note=form.cleaned_data.get("note", ""), created_by=request.user,
                )
                messages.success(request, _("Mouvement enregistré."))
            else:
                messages.error(request, _("Montant invalide."))
            return redirect("caisse_session")

        if action == "cloturer":
            form = CloturerSessionForm(request.POST)
            if form.is_valid():
                try:
                    services.cloturer_session(
                        session, form.cleaned_data["comptage_physique"],
                        note=form.cleaned_data.get("note", ""),
                        ip=request.META.get("REMOTE_ADDR"),
                    )
                    messages.success(request, _("Session clôturée (rapport Z édité)."))
                    if session.ecart and abs(session.ecart) > Decimal(
                        getattr(_settings(), "CAISSE_ECART_TOLERANCE", "500.00")
                    ):
                        messages.warning(
                            request,
                            _("Écart de %(ecart)s FCFA signalé au gérant (anomalie enregistrée).")
                            % {"ecart": f"{session.ecart:,.2f}"},
                        )
                except services.CaisseError as exc:
                    messages.error(request, str(exc))
            else:
                messages.error(request, _("Comptage physique invalide."))
            return redirect("caisse_session")

        messages.error(request, _("Action inconnue."))
        return redirect("caisse_session")


# ═══════════════════════════════════════════════════════════════════════════
# Ventes — historique, tickets, annulation
# ═══════════════════════════════════════════════════════════════════════════
class CaisseVentesListView(CaissierRequiredMixin, ListView):

    template_name = "caisse/ventes.html"
    context_object_name = "ventes"
    paginate_by = 25

    def get_queryset(self):
        qs = Vente.objects.select_related("session", "vendeur").prefetch_related("lignes", "paiements")
        if not self.request.user.is_comptable_or_higher():
            qs = qs.filter(vendeur=self.request.user)
        ref = self.request.GET.get("q", "").strip()
        if ref:
            qs = qs.filter(reference__icontains=ref)
        statut = self.request.GET.get("statut", "").strip()
        if statut:
            qs = qs.filter(statut=statut)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = self.request.GET.get("q", "")
        ctx["statut"] = self.request.GET.get("statut", "")
        return ctx


class _VenteTicketMixin(CaissierRequiredMixin):
    """Accès ticket : son auteur ou Comptable+."""

    def get_vente(self, reference: str) -> Vente:
        vente = get_object_or_404(
            Vente.objects.select_related("session", "vendeur").prefetch_related(
                "lignes", "paiements"
            ),
            reference=reference,
        )
        if not self.request.user.is_comptable_or_higher() and vente.vendeur_id != self.request.user.pk:
            raise Http404("Vente non accessible.")
        return vente


class CaisseTicketPDFView(_VenteTicketMixin, View):
    """Ticket PDF au format rouleau (58/80 mm) — POS-05."""

    def get(self, request, reference: str):
        vente = self.get_vente(reference)
        width = 80 if request.GET.get("format") == "80" else 58
        response = HttpResponse(ticket_pdf(vente, width), content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="ticket-{vente.reference}.pdf"'
        return response


class CaisseTicketESCPOSView(_VenteTicketMixin, View):
    """Flux binaire ESC/POS prêt pour imprimante thermique (USB/Bluetooth)."""

    def get(self, request, reference: str):
        vente = self.get_vente(reference)
        width = 80 if request.GET.get("format") == "80" else 58
        response = FileResponse(
            io.BytesIO(ticket_escpos_bytes(vente, width)),
            content_type="application/octet-stream",
        )
        response["Content-Disposition"] = f'attachment; filename="ticket-{vente.reference}.bin"'
        return response


class CaisseTicketTextView(_VenteTicketMixin, View):
    """Aperçu texte du ticket (contrôle avant impression)."""

    def get(self, request, reference: str):
        vente = self.get_vente(reference)
        return HttpResponse(ticket_texte(vente), content_type="text/plain; charset=utf-8")


class CaisseVenteAnnulerView(ComptableRequiredMixin, View):
    """Annulation d'une vente : stock restitué, trésorerie neutralisée, audit."""

    def post(self, request, reference: str):
        vente = get_object_or_404(Vente, reference=reference)
        try:
            services.annuler_vente(vente, user=request.user, ip=request.META.get("REMOTE_ADDR"))
            messages.warning(
                request, _(f"Vente {vente.reference} annulée — stock et trésorerie ajustés.")
            )
        except services.CaisseError as exc:
            messages.error(request, str(exc))
        return redirect(request.META.get("HTTP_REFERER") or reverse("caisse_ventes"))


# ═══════════════════════════════════════════════════════════════════════════
# Catalogue produits (POS-01) — Comptable+
# ═══════════════════════════════════════════════════════════════════════════
class CaisseCatalogueView(ComptableRequiredMixin, ListView):
    """Gestion du catalogue : liste filtrable + création/édition + catégories."""

    template_name = "caisse/catalogue.html"
    context_object_name = "produits"
    paginate_by = 30

    def get_queryset(self):
        qs = Produit.objects.select_related("categorie")
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(designation__icontains=q) | qs.filter(reference__icontains=q) \
                | qs.filter(ean__icontains=q)
        cat = self.request.GET.get("cat", "").strip()
        if cat:
            qs = qs.filter(categorie_id=cat)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = self.request.GET.get("q", "")
        ctx["form"] = ProduitForm()
        ctx["form_categorie"] = CategorieForm()
        edit_pk = self.request.GET.get("edit", "")
        if edit_pk:
            produit = Produit.objects.filter(pk=edit_pk).first()
            if produit:
                ctx["form_edit"] = ProduitForm(instance=produit)
                ctx["edit_pk"] = edit_pk
        ctx["all_categories"] = Categorie.objects.all()
        return ctx

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action", "produit")
        if action == "categorie":
            form = CategorieForm(request.POST)
            if form.is_valid():
                cat = form.save()
                messages.success(request, _(f"Catégorie « {cat.nom} » créée."))
            else:
                messages.error(request, _("Nom de catégorie requis (unique)."))
            return redirect("caisse_catalogue")

        pk = request.POST.get("pk")
        instance = Produit.objects.filter(pk=pk).first() if pk else None
        form = ProduitForm(request.POST, request.FILES, instance=instance)
        if form.is_valid():
            try:
                produit = form.save()
                messages.success(
                    request,
                    _(f"Produit « {produit.designation} » enregistré ({produit.reference}).")
                )
            except IntegrityError:
                messages.error(request, _("Référence ou EAN déjà utilisé."))
        else:
            msg = "; ".join(f"{k}: {v}" for k, v in form.errors.items())
            messages.error(request, _(f"Produit invalide — {msg}"))
        return redirect("caisse_catalogue")


CSV_COLUMNS = ["reference", "ean", "designation", "categorie", "unite",
               "prix_ttc", "tva_taux", "cout_achat", "stock", "seuil_alerte", "actif"]


class CaisseCatalogueExportView(ComptableRequiredMixin, View):
    """Export CSV du référentiel (importable dans un tableur)."""

    def get(self, request):
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="catalogue_monexa.csv"'
        writer = csv.writer(response, delimiter=";")
        writer.writerow(CSV_COLUMNS)
        for p in Produit.objects.select_related("categorie"):
            writer.writerow([
                p.reference, p.ean, p.designation,
                p.categorie.nom if p.categorie else "", p.unite,
                str(p.prix_ttc), str(p.tva_taux),
                str(p.cout_achat or ""), str(p.stock), str(p.seuil_alerte),
                "1" if p.actif else "0",
            ])
        return response


class CaisseCatalogueImportView(ComptableRequiredMixin, View):
    """
    Import CSV du référentiel (POS-01 : « import de 500 articles sans
    erreur »). Colonnes : reference;ean;designation;categorie;unite;prix_ttc;
    tva_taux;cout_achat;stock;seuil_alerte;actif — référence existante =
    mise à jour, sinon création.
    """

    def post(self, request):
        f = request.FILES.get("fichier")
        if not f:
            messages.error(request, _("Aucun fichier CSV fourni."))
            return redirect("caisse_catalogue")
        created = updated = skipped = 0
        try:
            text = f.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            text = f.read().decode("latin-1", errors="replace")
        reader = csv.reader(io.StringIO(text), delimiter=_sniff_delim(text))
        rows = list(reader)
        if not rows:
            messages.error(request, _("Fichier vide."))
            return redirect("caisse_catalogue")
        header = [h.strip().lower() for h in rows[0]]
        if "designation" not in header or "prix_ttc" not in header:
            messages.error(
                request,
                _("En-têtes attendus : reference;ean;designation;categorie;unite;"
                  "prix_ttc;tva_taux;cout_achat;stock;seuil_alerte;actif")
            )
            return redirect("caisse_catalogue")
        idx = {name: i for i, name in enumerate(header)}

        for row in rows[1:]:
            if len(row) < len(header) or not row[idx["designation"]].strip():
                skipped += 1
                continue
            try:
                cat = None
                cat_name = row[idx.get("categorie", 99)].strip() if "categorie" in idx else ""
                if cat_name:
                    cat, _cat_created = Categorie.objects.get_or_create(nom=cat_name)
                defaults = {
                    "designation": row[idx["designation"]].strip(),
                    "ean": row[idx["ean"]].strip() if "ean" in idx and row[idx["ean"]].strip() else "",
                    "unite": row[idx["unite"]].strip() if "unite" in idx and row[idx["unite"]].strip() else "pièce",
                    "prix_ttc": _dec(row[idx["prix_ttc"]].strip() or "0"),
                    "tva_taux": _dec(row[idx["tva_taux"]].strip() or "18"),
                    "stock": _dec(row[idx["stock"]].strip() or "0") if "stock" in idx else Decimal("0"),
                    "seuil_alerte": _dec(row[idx["seuil_alerte"]].strip() or "0") if "seuil_alerte" in idx else Decimal("0"),
                    "actif": row[idx["actif"]].strip() not in ("0", "false", "non", "") if "actif" in idx else True,
                }
                ca = row[idx["cout_achat"]].strip() if "cout_achat" in idx else ""
                defaults["cout_achat"] = _dec(ca) if ca else None
                # Ne pas écraser la catégorie d'un produit existant si la
                # colonne est vide sur la ligne d'import.
                if cat is not None:
                    defaults["categorie"] = cat
                ref = row[idx["reference"]].strip() if "reference" in idx else ""
                if ref:
                    _obj, was_created = Produit.objects.update_or_create(reference=ref, defaults=defaults)
                else:
                    _obj, was_created = Produit.objects.get_or_create(
                        designation=defaults["designation"], ean=defaults["ean"],
                        defaults={k: v for k, v in defaults.items() if k not in ("designation", "ean")},
                    )
                if was_created:
                    created += 1
                else:
                    updated += 1
            except (InvalidOperation, IndexError, IntegrityError):
                skipped += 1
        messages.success(
            request,
            _(f"Import terminé : {created} créés, {updated} mis à jour, {skipped} ignorés.")
        )
        return redirect("caisse_catalogue")


def _sniff_delim(text: str) -> str:
    first_line = text.split("\n", 1)[0]
    return ";" if first_line.count(";") >= first_line.count(",") else ","
