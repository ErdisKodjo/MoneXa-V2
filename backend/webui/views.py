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

import base64
import csv
import io

import qrcode
from django.contrib import messages
from django.contrib.auth import get_user_model, login as auth_login
from django.contrib.auth.views import LoginView as DjangoLoginView, LogoutView as DjangoLogoutView
from django.core.paginator import Paginator
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import CreateView, FormView, ListView, TemplateView
from django_otp import login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts.models import Notification
from auditing.models import AuditLog
from auditing.services import verify_chain
from assistant.services import answer_question
from finance.models import (
    Channel,
    Expense,
    GatewayTransaction,
    GatewayTransactionStatus,
    Invoice,
    MatchMethod,
    Payment,
    PaymentStatus,
    InvoiceStatus,
)
from finance.services.ai_pipeline import (
    extract_payment_from_image,
    extract_payment_from_text,
    pipeline_status,
)
from finance.services.anomalies import detect_anomalies, scan_recent_fraud, score_isolation_forest
from finance.services.gateways import (
    check_status,
    confirm_gateway_transaction,
    is_live,
    request_collection,
)
from finance.services.matcher import match_payment
from reporting.pdf import bilan_pdf, invoice_pdf, journal_caisse_pdf
from reporting.services import compute_kpis

from .forms import (
    AssistantQuestionForm,
    BankStatementForm,
    CollectionForm,
    ExpenseForm,
    InvoiceForm,
    MoneXaLoginForm,
    PaymentEvidenceForm,
    PaymentSmsForm,
    TOTPCodeForm,
)
from .mixins import CaissierRequiredMixin, ComptableRequiredMixin, GerantRequiredMixin

PAGE_SIZE = 15


# ═══════════════════════════════════════════════════════════════════════════
# Authentification (sessions — Django natif, CSRF protégé)
# ═══════════════════════════════════════════════════════════════════════════
class WebLoginView(DjangoLoginView):
    """Connexion web MVT — email + mot de passe, sessions Django.

    Si le compte a la 2FA TOTP activée, la connexion passe par une seconde
    étape (/login/totp/) avant l'ouverture de session effective.
    """

    template_name = "webui/login.html"
    authentication_form = MoneXaLoginForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        user = form.get_user()
        if user.is_2fa_enabled and user.totpdevice_set.filter(confirmed=True).exists():
            self.request.session["monexa_2fa_uid"] = user.pk
            self.request.session["monexa_2fa_at"] = timezone.now().isoformat()
            messages.info(
                self.request,
                _("Mot de passe accepté — saisissez le code de votre application d'authentification."),
            )
            return redirect("totp_login")
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

        # Fiabilité clients (v2.3) — score 0-100 par client
        from finance.services.client_scoring import client_reliability_scores

        ctx["client_scores"] = client_reliability_scores()

        # Alerte de tension de trésorerie (v2.3) — « ANTICIPER »
        from finance.services.tension import tension_alert

        ctx["tension"] = tension_alert()
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


class InvoicePDFView(CaissierRequiredMixin, View):
    """Facture PDF avec QR code de paiement T-Money / Moov / Flooz (v2.3)."""

    def get(self, request, pk: int):
        invoice = get_object_or_404(Invoice, pk=pk)
        data = invoice_pdf(invoice)
        response = HttpResponse(data, content_type="application/pdf")
        response["Content-Disposition"] = (
            f'attachment; filename="monexa_facture_{invoice.reference}.pdf"'
        )
        return response


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
        ctx["fraud"] = scan_recent_fraud(limit=200)
        ctx["ml_flagged"] = score_isolation_forest()
        ctx["total"] = len(rule_based) + len(ctx["fraud"]) + len(ctx["ml_flagged"])
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


# ═══════════════════════════════════════════════════════════════════════════
# 2FA TOTP — activation, confirmation, désactivation (Gérant)
# ═══════════════════════════════════════════════════════════════════════════
def _qr_data_uri(payload: str) -> str:
    """QR code (otpauth://) encodé en data URI PNG — aucun fichier disque."""
    img = qrcode.make(payload)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


class SecurityView(GerantRequiredMixin, TemplateView):
    """Page Sécurité — activation 2FA TOTP + diagnostic du pipeline IA."""

    template_name = "webui/security.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        ctx["is_2fa_enabled"] = user.is_2fa_enabled
        ctx["pending_device"] = user.totpdevice_set.filter(confirmed=False).first()
        ctx["active_device"] = user.totpdevice_set.filter(confirmed=True).first()
        ctx["totp_form"] = TOTPCodeForm()
        if ctx["pending_device"]:
            ctx["qr"] = _qr_data_uri(ctx["pending_device"].config_url)
        ctx["pipeline"] = pipeline_status()
        return ctx

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action", "")
        user = request.user

        if action == "enable":
            user.totpdevice_set.filter(confirmed=False).delete()
            TOTPDevice.objects.create(user=user, name="MoneXa Web", confirmed=False)
            messages.info(
                request,
                _("Scannez le QR code avec Google Authenticator / Authy, puis validez avec un code."),
            )
            return redirect("security")

        if action == "confirm":
            device = user.totpdevice_set.filter(confirmed=False).first()
            if not device:
                messages.error(request, _("Aucune activation en cours. Cliquez d'abord sur « Activer la 2FA »."))
                return redirect("security")
            form = TOTPCodeForm(request.POST)
            if form.is_valid() and device.verify_token(int(form.cleaned_data["code"])):
                device.confirmed = True
                device.save(update_fields=["confirmed"])
                user.is_2fa_enabled = True
                user.save(update_fields=["is_2fa_enabled"])
                messages.success(request, _("2FA activée — votre compte est protégé."))
            else:
                messages.error(request, _("Code invalide. Vérifiez l'heure de votre téléphone et réessayez."))
            return redirect("security")

        if action == "disable":
            user.totpdevice_set.all().delete()
            user.is_2fa_enabled = False
            user.save(update_fields=["is_2fa_enabled"])
            messages.warning(request, _("2FA désactivée — pensez à la réactiver après la démo."))
            return redirect("security")

        messages.error(request, _("Action inconnue."))
        return redirect("security")


class TOTPLoginView(FormView):
    """Seconde étape de connexion pour les comptes avec 2FA activée."""

    template_name = "webui/totp_login.html"
    form_class = TOTPCodeForm
    success_url = reverse_lazy("dashboard")

    def dispatch(self, request, *args, **kwargs):
        if not request.session.get("monexa_2fa_uid"):
            return redirect("login")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        User = get_user_model()
        ctx["pending_user"] = User.objects.filter(pk=self.request.session.get("monexa_2fa_uid")).first()
        return ctx

    def form_valid(self, form):
        User = get_user_model()
        uid = self.request.session.get("monexa_2fa_uid")
        user = User.objects.filter(pk=uid, is_active=True).first()
        if not user:
            self.request.session.pop("monexa_2fa_uid", None)
            return redirect("login")
        device = user.totpdevice_set.filter(confirmed=True).first()
        if device and device.verify_token(int(form.cleaned_data["code"])):
            auth_login(self.request, user)
            otp_login(self.request, device)  # django_otp : user.is_verified() = True
            self.request.session.pop("monexa_2fa_uid", None)
            self.request.session.pop("monexa_2fa_at", None)
            messages.success(
                self.request,
                _("Bienvenue %(name)s — 2FA validée.")
                % {"name": user.display_name},
            )
            return super().form_valid(form)
        form.add_error("code", _("Code incorrect ou expiré. Réessayez."))
        return self.form_invalid(form)


# ═══════════════════════════════════════════════════════════════════════════
# Notifications in-app — cloche + page + marquage lu
# ═══════════════════════════════════════════════════════════════════════════
class NotificationsView(CaissierRequiredMixin, ListView):
    template_name = "webui/notifications.html"
    context_object_name = "notifications"
    paginate_by = 20

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user).order_by("-created_at")


class NotificationReadView(CaissierRequiredMixin, View):
    """POST /notifications/<pk>/lu/ — marque une notification comme lue."""

    def post(self, request, pk):
        notification = get_object_or_404(Notification, pk=pk, user=request.user)
        notification.is_read = True
        notification.save(update_fields=["is_read"])
        return redirect("notifications")


# ═══════════════════════════════════════════════════════════════════════════
# Encaissements Mobile Money — collecte T-Money / Moov / Flooz (Comptable+)
# ═══════════════════════════════════════════════════════════════════════════
class CollectionView(ComptableRequiredMixin, TemplateView):
    """Encaisser une facture par Mobile Money (push client) + suivi statuts."""

    template_name = "webui/collections.html"

    def _refresh_pending(self, request):
        """Rafraîchit les collections en attente ; à SUCCESS → paiement + réconciliation."""
        for gt in GatewayTransaction.objects.filter(status=GatewayTransactionStatus.PENDING)[:20]:
            check_status(gt)
            if gt.status == GatewayTransactionStatus.SUCCESS:
                confirm_gateway_transaction(gt)
                messages.success(
                    request,
                    _("Collection %(tx)s confirmée — paiement créé et passé en réconciliation.")
                    % {"tx": gt.gateway_tx_id},
                )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        self._refresh_pending(self.request)
        ctx["form"] = CollectionForm()
        ctx["transactions"] = GatewayTransaction.objects.select_related("invoice", "initiated_by")[:30]
        ctx["live_modes"] = {
            op: is_live(op) for op in ("TMONEY", "MOOV", "FLOOZ")
        }
        return ctx

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action", "")

        if action == "request":
            form = CollectionForm(request.POST)
            if form.is_valid():
                gt = request_collection(
                    invoice=form.cleaned_data["invoice"],
                    operator=form.cleaned_data["operator"],
                    phone=form.cleaned_data["phone"],
                    initiated_by=request.user,
                )
                mode = _("production") if not gt.is_sandbox else _("sandbox")
                messages.success(
                    request,
                    _("Demande envoyée au client (%(mode)s) — référence opérateur %(tx)s.")
                    % {"mode": mode, "tx": gt.gateway_tx_id},
                )
            else:
                messages.error(request, _("Formulaire invalide : vérifiez la facture, l'opérateur et le numéro."))
            return redirect("collections")

        if action == "simulate":
            gt = get_object_or_404(
                GatewayTransaction, pk=request.POST.get("pk", 0)
            )
            if gt.is_sandbox and gt.status == GatewayTransactionStatus.PENDING:
                gt.status = GatewayTransactionStatus.SUCCESS
                gt.raw_response = {
                    **gt.raw_response,
                    "sandbox_confirmed_at": timezone.now().isoformat(),
                    "message": "Validation client simulée (bouton démo).",
                }
                gt.save(update_fields=["status", "raw_response", "updated_at"])
                confirm_gateway_transaction(gt)
                messages.success(
                    request,
                    _("Validation client simulée — paiement %(amount)s FCFA créé et réconcilié.")
                    % {"amount": gt.amount},
                )
            else:
                messages.error(request, _("Seule une collection sandbox en attente peut être simulée."))
            return redirect("collections")

        messages.error(request, _("Action inconnue."))
        return redirect("collections")


# ═══════════════════════════════════════════════════════════════════════════
# Exports PDF — journal de caisse + bilan (Comptable+)
# ═══════════════════════════════════════════════════════════════════════════
class JournalCaissePDFView(ComptableRequiredMixin, View):
    def get(self, request):
        data = journal_caisse_pdf(Payment.objects.all())
        response = HttpResponse(data, content_type="application/pdf")
        response["Content-Disposition"] = 'attachment; filename="monexa_journal_caisse.pdf"'
        return response


class BilanPDFView(ComptableRequiredMixin, View):
    def get(self, request):
        try:
            days = int(request.GET.get("days", 30))
        except (TypeError, ValueError):
            days = 30
        days = max(1, min(days, 365))
        data = bilan_pdf(days=days)
        response = HttpResponse(data, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="monexa_bilan_{days}j.pdf"'
        return response


# ═══════════════════════════════════════════════════════════════════════════
# Banque — rapprochement multi-comptes par import de relevé CSV (v2.3)
# ═══════════════════════════════════════════════════════════════════════════
class BankImportView(ComptableRequiredMixin, FormView):
    """
    GET/POST /banque/ — upload du relevé CSV, rapprochement automatique
    via la cascade de matching, rapport détaillé en session.

    Règle : toute écriture financière est transactionnelle et idempotente
    (provider_ref BQ-… unique — un relevé ré-importé ne crée rien).
    """
    template_name = "webui/bank.html"
    form_class = BankStatementForm
    success_url = reverse_lazy("bank")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["report"] = self.request.session.pop("bank_report", None)
        ctx["details"] = self.request.session.pop("bank_report_details", [])
        return ctx

    def form_valid(self, form):
        from finance.services.bank_reconcile import (
            parse_bank_csv,
            reconcile_bank_statement,
        )

        csv_bytes = form.cleaned_data["statement"].read()
        lines, errors, debits_ignored = parse_bank_csv(csv_bytes)
        if not lines and not errors:
            errors = ["Aucune ligne CRÉDIT exploitable trouvée dans le fichier."]
        report = reconcile_bank_statement(
            lines,
            created_by=self.request.user,
            debits_ignored=debits_ignored,
            errors=errors,
        )
        self.request.session["bank_report"] = report.as_dict()
        self.request.session["bank_report_details"] = report.details[:100]

        if report.imported:
            messages.success(
                self.request,
                _("Relevé importé : %(imported)s encaissement(s) créé(s), "
                  "%(matched)s rapproché(s) automatiquement, "
                  "%(skipped)s doublon(s) ignoré(s).")
                % {
                    "imported": report.imported,
                    "matched": report.matched_ref + report.matched_amount + report.matched_fuzzy,
                    "skipped": report.skipped,
                },
            )
        else:
            messages.warning(
                self.request,
                _("Aucun nouvel encaissement importé (%(skipped)s doublon(s) "
                  "déjà présent(s), %(errors)s erreur(s)).")
                % {"skipped": report.skipped, "errors": len(report.errors)},
            )
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.error(self.request, _("Fichier refusé : vérifiez le format CSV."))
        return super().form_invalid(form)
