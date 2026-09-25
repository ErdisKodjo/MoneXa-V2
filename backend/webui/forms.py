"""
Formulaires Django (couche MVT) — validation serveur native, jamais de démo.

Règles d'or financières respectées :
- Montants en DecimalField (jamais de float)
- Validation métier dans clean_*()
- Dates systématiquement validées (échéance >= émission)
"""
from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.utils.translation import gettext_lazy as _

from finance.models import Invoice, Expense, Channel, ExpenseCategory


class MoneXaLoginForm(AuthenticationForm):
    """Connexion par email (USERNAME_FIELD = email)."""

    username = forms.EmailField(
        label=_("Adresse email"),
        widget=forms.EmailInput(
            attrs={
                "class": "input",
                "placeholder": "vous@entreprise.tg",
                "autocomplete": "email",
                "autofocus": True,
            }
        ),
    )
    password = forms.CharField(
        label=_("Mot de passe"),
        widget=forms.PasswordInput(
            attrs={"class": "input", "placeholder": "••••••••", "autocomplete": "current-password"}
        ),
    )

    error_messages = {
        "invalid_login": _(
            "Email ou mot de passe incorrect. Vérifiez vos identifiants."
        ),
        "inactive": _("Ce compte est désactivé. Contactez le Gérant."),
    }


class InvoiceForm(forms.ModelForm):
    """Création de facture — référence FACT-YYYY-XXXX auto-générée au save()."""

    class Meta:
        model = Invoice
        fields = ["client_name", "client_phone", "amount", "issue_date", "due_date"]
        widgets = {
            "client_name": forms.TextInput(
                attrs={"class": "input", "placeholder": "Nom du client"}
            ),
            "client_phone": forms.TextInput(
                attrs={"class": "input", "placeholder": "+228 90 00 00 00"}
            ),
            "amount": forms.NumberInput(
                attrs={"class": "input", "step": "0.01", "min": "1", "placeholder": "0.00"}
            ),
            "issue_date": forms.DateInput(
                attrs={"class": "input", "type": "date"}, format="%Y-%m-%d"
            ),
            "due_date": forms.DateInput(
                attrs={"class": "input", "type": "date"}, format="%Y-%m-%d"
            ),
        }

    def clean_amount(self):
        from decimal import Decimal, InvalidOperation

        amount = self.cleaned_data.get("amount")
        try:
            if amount is not None and amount <= Decimal("0"):
                raise forms.ValidationError(_("Le montant doit être strictement positif."))
        except (InvalidOperation, TypeError):
            raise forms.ValidationError(_("Montant invalide."))
        return amount

    def clean(self):
        cleaned = super().clean()
        issue_date = cleaned.get("issue_date")
        due_date = cleaned.get("due_date")
        if issue_date and due_date and due_date < issue_date:
            self.add_error("due_date", _("La date d'échéance ne peut pas précéder la date d'émission."))
        return cleaned


class ExpenseForm(forms.ModelForm):
    """Saisie de dépense (flux sortants)."""

    class Meta:
        model = Expense
        fields = ["supplier", "category", "amount", "paid_at", "note"]
        widgets = {
            "supplier": forms.TextInput(
                attrs={"class": "input", "placeholder": "Fournisseur / bénéficiaire"}
            ),
            "category": forms.Select(attrs={"class": "input"}),
            "amount": forms.NumberInput(
                attrs={"class": "input", "step": "0.01", "min": "1", "placeholder": "0.00"}
            ),
            "paid_at": forms.DateTimeInput(
                attrs={"class": "input", "type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
            "note": forms.Textarea(
                attrs={"class": "input", "rows": 2, "placeholder": "Note optionnelle"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].choices = [("", "— Choisir —")] + list(
            ExpenseCategory.choices
        )

    def clean_amount(self):
        from decimal import Decimal

        amount = self.cleaned_data.get("amount")
        if amount is not None and amount <= Decimal("0"):
            raise forms.ValidationError(_("Le montant doit être strictement positif."))
        return amount


class PaymentSmsForm(forms.Form):
    """Saisie manuelle du texte SMS Mobile Money (fallback hors-ligne IA)."""

    text = forms.CharField(
        label=_("Texte du SMS de confirmation"),
        widget=forms.Textarea(
            attrs={
                "class": "input",
                "rows": 4,
                "placeholder": _(
                    "Collez ici le SMS de confirmation T-Money / Moov / Flooz…"
                ),
            }
        ),
    )


class PaymentEvidenceForm(forms.Form):
    """Upload d'une photo de reçu Mobile Money → pipeline IA."""

    image = forms.ImageField(
        label=_("Photo du reçu"),
        widget=forms.ClearableFileInput(attrs={"class": "input", "accept": "image/*"}),
    )


class AssistantQuestionForm(forms.Form):
    """Question en langage naturel pour TresorIA."""

    question = forms.CharField(
        max_length=500,
        label=_("Votre question"),
        widget=forms.TextInput(
            attrs={
                "class": "input",
                "placeholder": _("Ex. : Combien ai-je en T-Money ?"),
                "autocomplete": "off",
            }
        ),
    )


class PaymentDecisionForm(forms.Form):
    """Décision comptable sur un paiement A_VALIDER."""

    DECISIONS = [
        ("RECONCILIE", _("Réconcilier")),
        ("ANOMALIE", _("Signaler une anomalie")),
    ]
    decision = forms.ChoiceField(choices=DECISIONS, widget=forms.HiddenInput())


class TOTPCodeForm(forms.Form):
    """Code TOTP à 6 chiffres (activation 2FA ou seconde étape de connexion)."""

    code = forms.CharField(
        label=_("Code d'authentification"),
        min_length=6,
        max_length=8,
        widget=forms.TextInput(
            attrs={
                "class": "input",
                "inputmode": "numeric",
                "pattern": r"\d{6,8}",
                "autocomplete": "one-time-code",
                "placeholder": "123456",
                "autofocus": True,
            }
        ),
    )

    def clean_code(self):
        return self.cleaned_data["code"].replace(" ", "").strip()


class CollectionForm(forms.Form):
    """Demande d'encaissement Mobile Money (push USSD vers le client)."""

    OPERATORS = [
        ("TMONEY", "T-Money"),
        ("MOOV", "Moov Money"),
        ("FLOOZ", "Flooz"),
    ]
    invoice = forms.ModelChoiceField(
        label=_("Facture à encaisser"),
        queryset=Invoice.objects.none(),
        widget=forms.Select(attrs={"class": "input"}),
    )
    operator = forms.ChoiceField(
        label=_("Opérateur"), choices=OPERATORS, widget=forms.Select(attrs={"class": "input"})
    )
    phone = forms.RegexField(
        label=_("Téléphone du client"),
        regex=r"^(\+?228[\s.\-]?)?[79]\d[\s.\-]?\d{2}[\s.\-]?\d{2}[\s.\-]?\d{2}$",
        widget=forms.TextInput(attrs={"class": "input", "placeholder": "90 12 34 56"}),
        error_messages={"invalid": _("Numéro togolais attendu (ex. 90 12 34 56).")},
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from finance.models import InvoiceStatus

        self.fields["invoice"].queryset = Invoice.objects.filter(
            status=InvoiceStatus.EN_ATTENTE
        ).order_by("-issue_date")

    def clean_phone(self):
        digits = "".join(ch for ch in self.cleaned_data["phone"] if ch.isdigit())
        if len(digits) > 8:
            digits = digits[-8:]
        return digits


# Champs de filtre réutilisables ------------------------------------------------

STATUS_FILTER_CHOICES = None  # renseigné dynamiquement dans les vues
CHANNEL_FILTER_CHOICES = Channel.choices
