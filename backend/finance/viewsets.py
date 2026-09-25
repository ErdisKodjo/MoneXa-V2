"""
Finance viewsets — Invoice, Payment (with IA evidence endpoint), Account, Expense.
"""
from __future__ import annotations
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.permissions import (
    IsCaissierOrHigher, IsComptableOrHigher, IsOwnerOrComptableOrHigher,
)
from .models import Account, Invoice, Payment, Expense, ForecastCache, MatchMethod, PaymentStatus
from .serializers import (
    AccountSerializer, InvoiceSerializer, PaymentSerializer, ExpenseSerializer,
)
from .services.ai_pipeline import extract_payment_from_image, extract_payment_from_text
from .services.matcher import match_payment
from .services.anomalies import detect_anomalies


class AccountViewSet(viewsets.ReadOnlyModelViewSet):
    """GET /api/accounts/ — list treasury accounts (read-only)."""
    queryset = Account.objects.filter(is_active=True).order_by("channel", "name")
    serializer_class = AccountSerializer
    permission_classes = [IsComptableOrHigher]
    filterset_fields = ["channel"]


class InvoiceViewSet(viewsets.ModelViewSet):
    """
    /api/invoices/ — CRUD with role-based scoping.

    - CAISSIER sees own invoices, can create
    - COMPTABLE+ sees all
    """
    queryset = Invoice.objects.all().order_by("-issue_date")
    serializer_class = InvoiceSerializer
    permission_classes = [IsCaissierOrHigher, IsOwnerOrComptableOrHigher]
    filterset_fields = ["status", "client_name", "issue_date"]
    search_fields = ["reference", "client_name", "client_phone"]
    ordering_fields = ["issue_date", "due_date", "amount"]

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.user.is_comptable_or_higher():
            return qs
        return qs.filter(created_by=self.request.user)

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=["patch"], url_path="validate",
            permission_classes=[IsComptableOrHigher])
    def validate_invoice(self, request, pk=None):
        """Mark an invoice as RECONCILIE."""
        invoice = self.get_object()
        invoice.status = "RECONCILIE"
        invoice.save(update_fields=["status", "updated_at"])
        return Response(InvoiceSerializer(invoice).data)


class PaymentViewSet(viewsets.ModelViewSet):
    """
    /api/payments/

    Endpoints:
    - GET    /payments/                  — list (CAISSIER sees own, COMPTABLE+ sees all)
    - POST   /payments/                  — manual creation
    - POST   /payments/evidence/         — upload image → IA pipeline → matcher
    - POST   /payments/manual-text/      — fallback : paste SMS text
    - PATCH  /payments/{id}/validate/    — COMPTABLE+ validates a payment
    - GET    /payments/?status=A_VALIDER — file d'attente
    """
    queryset = Payment.objects.all().order_by("-paid_at")
    serializer_class = PaymentSerializer
    permission_classes = [IsCaissierOrHigher, IsOwnerOrComptableOrHigher]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    filterset_fields = ["status", "channel", "match_method"]
    search_fields = ["provider_ref", "payer_name", "payer_phone"]
    ordering_fields = ["paid_at", "amount", "anomaly_score"]

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.user.is_comptable_or_higher():
            return qs
        return qs.filter(created_by=self.request.user)

    def perform_create(self, serializer):
        with transaction.atomic():
            payment = serializer.save(created_by=self.request.user)
            # Run matcher immediately
            new_status, invoice, method = match_payment(payment)
            payment.status = new_status
            payment.match_method = method
            if invoice:
                payment.invoice = invoice
            payment.save()
            # Audit will be handled by signal

    @action(detail=False, methods=["post"], url_path="evidence",
            permission_classes=[IsCaissierOrHigher])
    def upload_evidence(self, request):
        """
        POST /api/payments/evidence/
        Upload an image of a Mobile Money receipt → run IA pipeline → create payment.

        Body: multipart/form-data with `image` file
        """
        image_file = request.FILES.get("image")
        if not image_file:
            return Response(
                {"detail": "Aucune image fournie. Champ attendu: image."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        image_bytes = image_file.read()
        try:
            extracted = extract_payment_from_image(image_bytes, image_file.name)
        except Exception as e:
            return Response(
                {"detail": f"Échec de l'extraction IA: {str(e)}"},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        with transaction.atomic():
            # Check for duplicate provider_ref
            if Payment.objects.filter(provider_ref=extracted["reference"]).exists():
                return Response(
                    {
                        "detail": "Doublon détecté: ce provider_ref existe déjà.",
                        "provider_ref": extracted["reference"],
                    },
                    status=status.HTTP_409_CONFLICT,
                )

            # Save image to media
            from django.core.files.base import ContentFile
            image_file.seek(0)

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
            payment.evidence_image.save(image_file.name, ContentFile(image_file.read()), save=False)
            payment.save()

            # Run matcher
            new_status, invoice, method = match_payment(payment)
            payment.status = new_status
            payment.match_method = method
            if invoice:
                payment.invoice = invoice
            payment.save()

        return Response(PaymentSerializer(payment).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="manual-text",
            permission_classes=[IsCaissierOrHigher])
    def upload_manual_text(self, request):
        """
        POST /api/payments/manual-text/
        Fallback: paste SMS text directly.
        Body: {"text": "..."}
        """
        text = request.data.get("text", "").strip()
        if not text:
            return Response(
                {"detail": "Aucun texte fourni. Champ attendu: text."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            extracted = extract_payment_from_text(text)
        except Exception as e:
            return Response(
                {"detail": f"Échec de l'extraction: {str(e)}"},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        with transaction.atomic():
            if Payment.objects.filter(provider_ref=extracted["reference"]).exists():
                return Response(
                    {"detail": "Doublon détecté.",
                     "provider_ref": extracted["reference"]},
                    status=status.HTTP_409_CONFLICT,
                )

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
            payment.save()

            new_status, invoice, method = match_payment(payment)
            payment.status = new_status
            payment.match_method = method
            if invoice:
                payment.invoice = invoice
            payment.save()

        return Response(PaymentSerializer(payment).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["patch"], url_path="validate",
            permission_classes=[IsComptableOrHigher])
    def validate_payment(self, request, pk=None):
        """
        PATCH /api/payments/{id}/validate/
        COMPTABLE+ validates an A_VALIDER payment.
        Body: {"decision": "RECONCILIE" | "ANOMALIE"}
        """
        payment = self.get_object()
        decision = (
            request.data.get("decision")
            or request.data.get("action")
            or "RECONCILIE"
        )
        decision = str(decision).upper()
        if decision in ("APPROVE", "VALIDER", "RECONCILIE"):
            decision = "RECONCILIE"
        elif decision in ("REJECT", "REJET", "ANOMALIE", "NON_RATTACHE"):
            decision = "ANOMALIE"
        if decision not in ("RECONCILIE", "ANOMALIE"):
            return Response(
                {"detail": "decision doit être RECONCILIE ou ANOMALIE."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        payment.status = decision
        payment.save(update_fields=["status", "updated_at"])
        return Response(PaymentSerializer(payment).data)


class ExpenseViewSet(viewsets.ModelViewSet):
    """GET/POST /api/expenses/ — flux sortants."""
    queryset = Expense.objects.all().order_by("-paid_at")
    serializer_class = ExpenseSerializer
    permission_classes = [IsCaissierOrHigher, IsOwnerOrComptableOrHigher]
    filterset_fields = ["category", "paid_at"]
    search_fields = ["supplier"]

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.user.is_comptable_or_higher():
            return qs
        return qs.filter(created_by=self.request.user)

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
