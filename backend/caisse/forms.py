"""
Forms du module caisse (POS) — validation serveur systématique.
"""
from decimal import Decimal

from django import forms

from .models import Categorie, Produit, SessionCaisse


class ProduitForm(forms.ModelForm):
    class Meta:
        model = Produit
        fields = [
            "reference", "ean", "designation", "categorie", "unite",
            "prix_ttc", "tva_taux", "cout_achat", "stock", "seuil_alerte",
            "image", "actif",
        ]
        widgets = {
            "reference": forms.TextInput(attrs={"placeholder": "auto (ART-000001)"}),
            "ean": forms.TextInput(attrs={"placeholder": "13 chiffres, scannable"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields:
            self.fields[f].widget.attrs.setdefault("class", "input")
        self.fields["reference"].required = False  # auto-générée si vide

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("reference"):
            cleaned["reference"] = ""  # → generate_reference() au save
        return cleaned


class CategorieForm(forms.ModelForm):
    class Meta:
        model = Categorie
        fields = ["nom", "couleur"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["nom"].widget.attrs.setdefault("class", "input")
        self.fields["couleur"].widget.attrs.setdefault("type", "color")


class OuvrirSessionForm(forms.Form):
    """Ouverture de caisse — fond de caisse déclaré (POS-06)."""

    fond_caisse = forms.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0"),
        label="Fond de caisse (FCFA)", initial=Decimal("0"),
        widget=forms.NumberInput(attrs={"class": "input", "step": "0.01", "inputmode": "decimal"}),
    )


class CloturerSessionForm(forms.Form):
    """Clôture Z — comptage physique saisi, écart calculé par le système."""

    comptage_physique = forms.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0"),
        label="Comptage physique des espèces (FCFA)",
        widget=forms.NumberInput(attrs={"class": "input", "step": "0.01", "inputmode": "decimal"}),
    )
    note = forms.CharField(
        required=False, label="Note de clôture", max_length=500,
        widget=forms.Textarea(attrs={"class": "input", "rows": 2}),
    )


class MouvementCaisseForm(forms.Form):
    """Dépôt de sécurisation / retrait / dépense au comptant (POS-06)."""

    TYPES = [
        ("DEPOT", "Dépôt de sécurisation"),
        ("RETRAIT", "Retrait (fonds)"),
        ("DEPENSE", "Dépense au comptant"),
    ]
    type = forms.ChoiceField(choices=TYPES, widget=forms.Select(attrs={"class": "input"}))
    montant = forms.DecimalField(
        max_digits=12, decimal_places=2,
        widget=forms.NumberInput(attrs={"class": "input", "step": "0.01", "inputmode": "decimal"}),
    )
    note = forms.CharField(
        max_length=200, required=False,
        widget=forms.TextInput(attrs={"class": "input", "placeholder": "Motif (facultatif)"}),
    )
