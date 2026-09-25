"""
WebUI views — couche Django MVT fonctionnelle de MoneXa.

Chaque vue réutilise les services métier existants (jamais de logique dupliquée) :
- compute_kpis / forecast   → reporting.services, finance.services.forecast
- matcher / ai_pipeline     → finance.services
- detect_anomalies / ML     → finance.services.anomalies
- answer_question (TresorIA)→ assistant.services
- verify_chain (audit)      → auditing.verification

RBAC (docs/rbac-matrix.md) :
- Dashboard, factures, paiements, dépenses : connecté (Caissier voit les siens)
- Validation paiements, exports            : Comptable+
- Anomalies, journal d'audit               : Gérant
"""
from __future__ import annotations

import csv
import io

from django.contrib import messages
from django.contrib.auth.views import LoginView as DjangoLoginView, LogoutView as DjangoLogoutView
from django.core.paginator import Paginator
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import CreateView, FormView, ListView, TemplateView

from auditing.models import AuditLog
from auditing.services import verify_chain
from assistant.services import answer_question
from finance.models import (
    Channel,
    Expense,
    Invoice,
    MatchMethod,
    Payment,
    PaymentStatus,
    InvoiceStatus,
)
from finance.services.ai_pipeline import extract_payment_from_image, extract_payment_from_text
from finance.services.anomalies import detect_anomalies, score_isolation_forest
from finance.services.matcher import match_payment
from reporting.services import compute_kpis

from .forms import (
    AssistantQuestionForm,
    ExpenseForm,
    InvoiceForm,
    MoneXaLoginForm,
    PaymentEvidenceForm,
    PaymentSmsForm,
)
from .mixins import CaissierRequiredMixin, ComptableRequiredMixin, GerantRequiredMixin

PAGE_SIZE = 15


# ═══════════════════════════════════════════════════════════════════════════
# Authentification (sessions — Django natif, CSRF protégé)
# ═══════════════════════════════════════════════════════════════════════════
class WebLoginView(DjangoLoginView):
    """Connexion web MVT — email + mot de passe, sessions Django."""

    template_name = "webui/login.html"
    authentication_form = MoneXaLoginForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        messages.success(
            self.request,
            _("Bienvenue %(name)s — rôle : %(role)s.")
            % {"name": form.get_user().display_name, "role": form.get_user().get_role_display()},
        )
        return super().form_valid(form)


class WebLogoutView(DjangoLogoutView):
    """Déconnexion POST (CSRF-safe)."""

    next_page = "login"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            messages.info(request, _("Vous êtes déconnecté. À bientôt !"))
        return super().dispatch(request, *args, **kwargs)


# ═══════════════════════════════════════════════════════════════════════════
# Dashboard — KPIs temps réel + graphes (CSS pur, aucune dépendance JS)
# ═══════════════════════════════════════════════════════════════════════════
class DashboardView(CaissierRequiredMixin, TemplateView):
    template_name = "webui/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        kpis = compute_kpis()

        # Barres flux 7j / 30j — pourcentages pré-calculés (graphes CSS)
        flux_items = [
            (_("Encaissé 7j"), kpis["encaisse_7j"], "success"),
            (_("Décaissé 7j"), kpis["decaisse_7j"], "danger"),
            (_("Encaissé 30j"), kpis["encaisse_30j"], "success"),
            (_("Décaissé 30j"), kpis["decaisse_30j"], "danger"),
        ]
        flux_max = max((v for _, v, _ in flux_items), default=0) or 1
        kpis["flux_bars"] = [
            {"label": label, "value": value, "pct": round(100 * value / flux_max, 1), "tone": tone}
            for label, value, tone in flux_items
        ]

        # Barres soldes par canal — couleurs de la charte
        canal_max = max(kpis["solde_par_canal"].values(), default=0) or 1
        canal_colors = {
            "TMONEY": "canal-tmoney", "MOOV": "canal-moov", "FLOOZ": "canal-flooz",
            "BANQUE": "canal-banque", "ESPECES": "canal-especes",
        }
        kpis["canal_bars"] = [
            {
                "code": code,
                "label": Channel(code).label if code in Channel.values else code,
                "value": value,
                "pct": round(100 * value / canal_max, 1),
                "tone": canal_colors.get(code, "canal-banque"),
            }
            for code, value in kpis["solde_par_canal"].items()
        ]

        ctx["kpis"] = kpis
        return ctx


# ═══════════════════════════════════════════════════════════════════════════
# Factures — liste filtrée + création (référence auto FACT-YYYY-XXXX)
# ═══════════════════════════════════════════════════════════════════════════
class InvoiceListView(CaissierRequiredMixin, ListView):
    template_name = "webui/invoices.html"
    context_object_name = "invoices"
    paginate_by = PAGE_SIZE

    def get_queryset(self):
        qs = Invoice.objects.all().order_by("-issue_date", "-id")
        if not self.request.user.is_comptable_or_higher():
            qs = qs.filter(created_by=self.request.user)
        status = self.request.GET.get("status", "")
        if status in InvoiceStatus.values:
            qs = qs.filter(status=status)
        q = self.request.GET.get("q", "").strip()
        if q:
            from django.db.models import Q

            qs = qs.filter(Q(reference__icontains=q) | Q(client_name__icontains=q) | Q(client_phone__icontains=q))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        qs = self.get_queryset()
        ctx["total_amount"] = sum(i.amount for i in qs) if hasattr(qs, "aggregate") is False else None
        # Compteurs par statut (badges)
        base = Invoice.objects.all()
        if not self.request.user.is_comptable_or_higher():
            base = base.filter(created_by=self.request.user)
        ctx["status_counts"] = {
            s.value: base.filter(status=s.value).count()
            for s in InvoiceStatus
        }
        ctx["status_choices"] = InvoiceStatus.choices
        ctx["current_status"] = self.request.GET.get("status", "")
        ctx["current_q"] = self.request.GET.get("q", "")
        return ctx


class InvoiceCreateView(CaissierRequiredMixin, CreateView):
    model = Invoice
    form_class = InvoiceForm
    template_name = "webui/invoice_form.html"
    success_url = reverse_lazy("invoices")

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        response = super().form_valid(form)
        messages.success(
            self.request,
            _("Facture %(ref)s créée pour %(client)s.")
            % {"ref": self.object.reference, "client": self.object.client_name},
        )
        return response

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["next_reference"] = Invoice.generate_reference()
        return ctx


# ═══════════════════════════════════════════════════════════════════════════
# Paiements — file de réconciliation, upload preuve IA, saisie SMS, validation
# ═══════════════════════════════════════════════════════════════════════════
class PaymentListView(CaissierRequiredMixin, ListView):
    template_name = "webui/payments.html"
    context_object_name = "payments"
    paginate_by = PAGE_SIZE

    def get_queryset(self):
        qs = Payment.objects.select_related("invoice", "created_by").order_by("-paid_at")
        if not self.request.user.is_comptable_or_higher():
            qs = qs.filter(created_by=self.request.user)
        status = self.request.GET.get("status", "")
        if status in PaymentStatus.values:
            qs = qs.filter(status=status)
        channel = self.request.GET.get("channel", "")
        if channel in Channel.values:
            qs = qs.filter(channel=channel)
        q = self.request.GET.get("q", "").strip()
        if q:
            from django.db.models import Q

            qs = qs.filter(
                Q(provider_ref__icontains=q) | Q(payer_name__icontains=q) | Q(payer_phone__icontains=q)
            )
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        base = Payment.objects.all()
        if not self.request.user.is_comptable_or_higher():
            base = base.filter(created_by=self.request.user)
        ctx["status_counts"] = {s.value: base.filter(status=s.value).count() for s in PaymentStatus}
        ctx["status_choices"] = PaymentStatus.choices
        ctx["channel_choices"] = Channel.choices
        ctx["current_status"] = self.request.GET.get("status", "")
        ctx["current_channel"] = self.request.GET.get("channel", "")
        ctx["current_q"] = self.request.GET.get("q", "")
        ctx["evidence_form"] = PaymentEvidenceForm()
        ctx["sms_form"] = PaymentSmsForm()
        ctx["can_validate"] = self.request.user.is_comptable_or_higher()
        return ctx


class PaymentDecisionView(ComptableRequiredMixin, View):
    """POST /paiements/<pk>/decision/ — Réconcilier ou Anomalie (comptable+)."""

    def post(self, request, pk):
        payment = get_object_or_404(Payment, pk=pk)
        decision = request.POST.get("decision", "")
        if decision == "RECONCILIE":
            payment.status = PaymentStatus.RECONCILIE
            payment.match_method = MatchMethod.MANUEL
            payment.save(update_fields=["status", "match_method", "updated_at"])
            messages.success(
                request,
                _("Paiement %(ref)s réconcilié.") % {"ref": payment.provider_ref},
            )
        elif decision == "ANOMALIE":
            payment.status = PaymentStatus.ANOMALIE
            payment.save(update_fields=["status", "updated_at"])
            messages.warning(
                request,
                _("Paiement %(ref)s signalé comme anomalie.") % {"ref": payment.provider_ref},
            )
        else:
            messages.error(request, _("Décision invalide."))
        return redirect("payments")


class _PaymentIngestMixin:
    """Partagé : ingestion d'un paiement (image ou SMS) → matcher → message."""

    def create_payment(self, extracted, request, image_file=None):
        from django.core.files.base import ContentFile

        with transaction.atomic():
            if Payment.objects.filter(provider_ref=extracted["reference"]).exists():
                messages.warning(
                    request,
                    _("Doublon détecté : la référence %(ref)s existe déjà.")
                    % {"ref": extracted["reference"]},
                )
                return None

            payment = Payment(
                provider_ref=extracted["reference"],
                amount=extracted["montant"],
                channel=extracted["operator"],
                payer_name=extracted["emetteur"],
                payer_phone=extracted["telephone_emetteur"] or "",
                paid_at=extracted["date_paiement"],
                raw_text=extracted["raw_text"],
                ai_confidence=extracted["ai_confidence"],
                created_by=request.user,
            )
            if image_file is not None:
                image_file.seek(0)
                payment.evidence_image.save(
                    image_file.name, ContentFile(image_file.read()), save=False
                )
            payment.save()

            new_status, invoice, method = match_payment(payment)
            payment.status = new_status
            payment.match_method = method
            if invoice:
                payment.invoice = invoice
            payment.save(update_fields=["status", "match_method", "invoice", "updated_at"])

            if new_status == PaymentStatus.RECONCILIE:
                messages.success(
                    request,
                    _("Paiement %(ref)s (%(amount)s FCFA) réconcilié automatiquement — %(method)s.")
                    % {
                        "ref": payment.provider_ref,
                        "amount": payment.amount,
                        "method": payment.get_match_method_display(),
                    },
                )
            elif new_status == PaymentStatus.ANOMALIE:
                messages.warning(
                    request,
                    _("Paiement %(ref)s enregistré avec anomalie — vérification requise.")
                    % {"ref": payment.provider_ref},
                )
            else:
                messages.info(
                    request,
                    _("Paiement %(ref)s enregistré — en file d'attente de validation.")
                    % {"ref": payment.provider_ref},
                )
            return payment


class PaymentEvidenceUploadView(CaissierRequiredMixin, _PaymentIngestMixin, View):
    """POST /paiements/preuve/ — photo de reçu → pipeline IA multimodal."""

    def post(self, request):
        form = PaymentEvidenceForm(request.POST, request.FILES)
        if not form.is_valid():
            messages.error(request, _("Veuillez choisir une image de reçu valide."))
            return redirect("payments")

        image_file = form.cleaned_data["image"]
        image_bytes = image_file.read()
        try:
            extracted = extract_payment_from_image(image_bytes, image_file.name)
        except Exception as exc:
            messages.error(
                request,
                _("Échec de l'extraction IA : %(err)s") % {"err": str(exc)[:120]},
            )
            return redirect("payments")

        self.create_payment(extracted, request, image_file=image_file)
        return redirect("payments")


class PaymentSmsView(CaissierRequiredMixin, _PaymentIngestMixin, View):
    """POST /paiements/sms/ — texte SMS collé manuellement (fallback)."""

    def post(self, request):
        form = PaymentSmsForm(request.POST)
        if not form.is_valid():
            messages.error(request, _("Veuillez coller le texte du SMS."))
            return redirect("payments")

        try:
            extracted = extract_payment_from_text(form.cleaned_data["text"])
        except Exception as exc:
            messages.error(
                request,
                _("Échec de l'analyse du SMS : %(err)s") % {"err": str(exc)[:120]},
            )
            return redirect("payments")

        self.create_payment(extracted, request)
        return redirect("payments")


# ═══════════════════════════════════════════════════════════════════════════
# Dépenses — liste + création
# ═══════════════════════════════════════════════════════════════════════════
class ExpenseListView(CaissierRequiredMixin, ListView):
    template_name = "webui/expenses.html"
    context_object_name = "expenses"
    paginate_by = PAGE_SIZE

    def get_queryset(self):
        qs = Expense.objects.select_related("created_by").order_by("-paid_at")
        if not self.request.user.is_comptable_or_higher():
            qs = qs.filter(created_by=self.request.user)
        category = self.request.GET.get("category", "")
        if category:
            qs = qs.filter(category=category)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form"] = ExpenseForm()
        qs = self.get_queryset()
        ctx["total_filtered"] = sum(e.amount for e in qs) if not hasattr(qs, "count") else None
        ctx["current_category"] = self.request.GET.get("category", "")
        return ctx


class ExpenseCreateView(CaissierRequiredMixin, CreateView):
    model = Expense
    form_class = ExpenseForm
    template_name = "webui/expense_form.html"
    success_url = reverse_lazy("expenses")

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        response = super().form_valid(form)
        messages.success(
            self.request,
            _("Dépense de %(amount)s FCFA enregistrée (%(supplier)s).")
            % {"amount": self.object.amount, "supplier": self.object.supplier},
        )
        return response


# ═══════════════════════════════════════════════════════════════════════════
# Anomalies — règles + Isolation Forest (Gérant)
# ═══════════════════════════════════════════════════════════════════════════
class AnomaliesView(GerantRequiredMixin, TemplateView):
    template_name = "webui/anomalies.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        rule_based = []
        for p in Payment.objects.filter(status=PaymentStatus.ANOMALIE).order_by("-paid_at")[:50]:
            for a in detect_anomalies(p):
                rule_based.append({
                    "payment": p,
                    "type": a.get("type", ""),
                    "description": a.get("description", ""),
                    "severity": a.get("severity", ""),
                })
        ctx["rule_based"] = rule_based
        ctx["ml_flagged"] = score_isolation_forest()
        ctx["total"] = len(rule_based) + len(ctx["ml_flagged"])
        return ctx


# ═══════════════════════════════════════════════════════════════════════════
# Journal d'audit immuable — hash-chain vérifiée en direct (Gérant)
# ═══════════════════════════════════════════════════════════════════════════
class AuditLogView(GerantRequiredMixin, ListView):
    template_name = "webui/audit.html"
    context_object_name = "logs"
    paginate_by = 30

    def get_queryset(self):
        qs = AuditLog.objects.select_related("user").order_by("-timestamp")
        action = self.request.GET.get("action", "").strip()
        if action:
            qs = qs.filter(action=action)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        chain_valid, broken = verify_chain()
        ctx["chain_valid"] = chain_valid
        ctx["broken_ids"] = [b.get("audit_log_id", "?") for b in broken]
        ctx["broken_details"] = broken
        ctx["actions"] = (
            AuditLog.objects.values_list("action", flat=True).distinct().order_by("action")
        )
        ctx["current_action"] = self.request.GET.get("action", "")
        return ctx


# ═══════════════════════════════════════════════════════════════════════════
# TresorIA — chatbot CFO (KPIs pré-calculés, jamais de SQL)
# ═══════════════════════════════════════════════════════════════════════════
class AssistantView(CaissierRequiredMixin, FormView):
    template_name = "webui/assistant.html"
    form_class = AssistantQuestionForm
    success_url = reverse_lazy("assistant")
    SESSION_KEY = "tresoria_history"
    HISTORY_MAX = 20

    def get(self, request, *args, **kwargs):
        form = self.get_form()
        return self.render_to_response(
            self.get_context_data(form=form, history=request.session.get(self.SESSION_KEY, []))
        )

    def post(self, request, *args, **kwargs):
        form = self.get_form()
        history = request.session.get(self.SESSION_KEY, [])
        if form.is_valid():
            question = form.cleaned_data["question"].strip()
            answer = answer_question(request.user, question)
            history.append({"role": "user", "text": question})
            history.append({"role": "bot", "text": answer})
            history = history[-self.HISTORY_MAX:]
            request.session[self.SESSION_KEY] = history
        return self.render_to_response(self.get_context_data(form=form, history=history))


# ═══════════════════════════════════════════════════════════════════════════
# Exports CSV — paiements et dépenses (Comptable+)
# ═══════════════════════════════════════════════════════════════════════════
class ExportsView(ComptableRequiredMixin, TemplateView):
    template_name = "webui/exports.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["nb_payments"] = Payment.objects.count()
        ctx["nb_expenses"] = Expense.objects.count()
        ctx["nb_invoices"] = Invoice.objects.count()
        return ctx


class _CsvExportView(ComptableRequiredMixin, View):
    filename_prefix = "monexa"

    def rows(self):
        raise NotImplementedError

    def get(self, request):
        buf = io.StringIO()
        writer = csv.writer(buf, delimiter=";")
        rows = self.rows()
        if rows:
            writer.writerow(rows[0].keys())
            for row in rows:
                writer.writerow(row.values())
        response = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{self.filename_prefix}.csv"'
        return response


class PaymentExportView(_CsvExportView):
    filename_prefix = "monexa_paiements"

    def rows(self):
        return [
            {
                "provider_ref": p.provider_ref,
                "amount": float(p.amount),
                "channel": p.get_channel_display(),
                "payer_name": p.payer_name,
                "payer_phone": p.payer_phone,
                "paid_at": p.paid_at.isoformat(),
                "status": p.get_status_display(),
                "match_method": p.get_match_method_display(),
                "ai_confidence": p.ai_confidence,
                "anomaly_score": p.anomaly_score,
            }
            for p in Payment.objects.select_related("invoice").order_by("-paid_at")
        ]


class ExpenseExportView(_CsvExportView):
    filename_prefix = "monexa_depenses"

    def rows(self):
        return [
            {
                "supplier": e.supplier,
                "category": e.get_category_display(),
                "amount": float(e.amount),
                "paid_at": e.paid_at.isoformat(),
                "note": e.note,
            }
            for e in Expense.objects.order_by("-paid_at")
        ]
