"""
Rapprochement bancaire multi-comptes — import de relevé CSV (v2.3).

Chantier « moyen terme — Rigueur financière » :
l'entreprise exporte le relevé de son compte bancaire (BAC, Ecobank,
Orabank… au format CSV) et MoneXa le rapproche automatiquement des
factures impayées en réutilisant la cascade de matching existante
(référence → montant+7j → fuzzy payeur → NON_RATTACHE).

Flux :
1. parse_bank_csv()        — lecture souple du CSV (délimiteur , ; ou tab,
                             formats de dates FR/ISO, montants FR/EN).
2. reconcile_bank_statement() — pour chaque ligne CRÉDIT :
   - idempotence : provider_ref « BQ-… » déjà présent → ligne ignorée ;
   - création Payment canal BANQUE + cascade de matching ;
   - rapport détaillé (importés, rapprochés par référence, par montant,
     fuzzy, non rattachés, erreurs).

Règles d'or respectées : DecimalField(14,2), transaction.atomic(),
provider_ref unique (anti-doublon natif — garantit l'idempotence).
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone as dj_timezone

from finance.models import Channel, MatchMethod, Payment, PaymentStatus
from finance.services.matcher import match_payment

# ──────────────────────────────────────────────────────────────────────────
# Parsing CSV souple
# ──────────────────────────────────────────────────────────────────────────

_HEADER_ALIASES = {
    "date": ("date", "date operation", "date_operation", "date de l'operation",
             "transaction date", "date valeur"),
    "libelle": ("libelle", "libellé", "description", "memo", "label", "detail",
                "operation", "nature"),
    "reference": ("reference", "référence", "ref", "id", "id transaction",
                  "transaction id", "piece"),
    "credit": ("credit", "crédit", "montant credit", "credit amount", "revenu"),
    "debit": ("debit", "débit", "montant debit", "debit amount", "retrait"),
    "montant": ("montant", "amount", "valeur", "solde operation", "credit-debit"),
}

_DATE_FORMATS = (
    "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%Y-%m-%d", "%d.%m.%Y",
)


@dataclass
class BankLine:
    """Une ligne CRÉDIT du relevé bancaire (candidat encaissement)."""
    date: datetime
    libelle: str
    montant: Decimal
    reference: str
    row: int
    extra_debit: Decimal = Decimal("0")  # débit sur la même ligne (info)


@dataclass
class BankReport:
    """Rapport de rapprochement affiché sur la page Banque."""
    total_lines: int = 0
    imported: int = 0
    skipped: int = 0
    matched_ref: int = 0
    matched_amount: int = 0
    matched_fuzzy: int = 0
    non_rattaches: int = 0
    debits_ignored: int = 0
    errors: list[str] = field(default_factory=list)
    details: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "total_lines": self.total_lines,
            "imported": self.imported,
            "skipped": self.skipped,
            "matched_ref": self.matched_ref,
            "matched_amount": self.matched_amount,
            "matched_fuzzy": self.matched_fuzzy,
            "non_rattaches": self.non_rattaches,
            "debits_ignored": self.debits_ignored,
            "errors": self.errors,
        }


def _normalize_header(h: str) -> str:
    return re.sub(r"\s+", " ", (h or "").strip().lower())


def _detect_columns(header: list[str]) -> dict[str, int]:
    """Mappe nom de colonne normalisé → index, via les alias connus."""
    cols: dict[str, int] = {}
    for idx, raw in enumerate(header):
        name = _normalize_header(raw)
        for key, aliases in _HEADER_ALIASES.items():
            if key in cols:
                continue
            if name in aliases or any(name.startswith(a) for a in aliases):
                cols[key] = idx
                break
    return cols


def _parse_date(raw: str) -> datetime | None:
    raw = (raw or "").strip()
    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(raw, fmt)
            return dj_timezone.make_aware(dt.replace(hour=12, minute=0))
        except ValueError:
            continue
    return None


def _parse_amount(raw: str) -> Decimal | None:
    """'1 234 567,89' / '1234567.89' / '1,234,567.89' / '50000 FCFA' → Decimal."""
    raw = (raw or "").strip().replace("FCFA", "").replace("XOF", "").strip()
    if not raw:
        return None
    cleaned = raw.replace(" ", "").replace("\u00a0", "")
    # Style FR : virgule décimale, points de milliers
    if "," in cleaned and "." not in cleaned:
        cleaned = cleaned.replace(",", ".")
    elif "," in cleaned and "." in cleaned:
        # Dernier séparateur = décimale
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    else:
        cleaned = cleaned.replace(",", "")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def parse_bank_csv(file_bytes: bytes) -> tuple[list[BankLine], list[str], int]:
    """
    Parse un relevé bancaire CSV.

    Returns:
        (lignes crédits, erreurs, nb débits ignorés)
    """
    text = file_bytes.decode("utf-8-sig", errors="replace")
    sample = text[:4096]
    delimiter = ";"
    try:
        sniffer = csv.Sniffer()
        detected = sniffer.sniff(sample, delimiters=";,\t").delimiter
        if detected:
            delimiter = detected
    except csv.Error:
        pass

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = [row for row in reader if any((c or "").strip() for c in row)]
    if not rows:
        return [], ["Fichier vide."], 0

    errors: list[str] = []
    debits_ignored = 0
    lines: list[BankLine] = []

    header = rows[0]
    cols = _detect_columns(header)
    has_header = "date" in cols and ("montant" in cols or "credit" in cols)
    data_rows = rows[1:] if has_header else rows
    if not has_header:
        # Mappage positionnel bancaire standard :
        # 3 colonnes : date ; libellé ; montant
        # 4 colonnes : date ; libellé ; référence ; montant
        # 5 colonnes : date ; libellé ; référence ; crédit ; débit
        if len(header) < 3:
            errors.append(
                "Colonnes non reconnues — attendu : date ; libellé ; "
                "référence ; crédit ; débit (ou au minimum date ; libellé ; montant)."
            )
            return [], errors, 0
        cols = {"date": 0, "libelle": 1}
        if len(header) >= 4:
            cols["reference"] = 2
            cols["credit"] = 3
        else:
            cols["credit"] = 2
        if len(header) >= 5:
            cols["debit"] = 4
        montant_i = -1
        credit_i = cols["credit"]
        debit_i = cols.get("debit", -1)

    date_i = cols.get("date", 0)
    lib_i = cols.get("libelle", 1)
    ref_i = cols.get("reference", -1)
    credit_i = cols.get("credit", -1)
    debit_i = cols.get("debit", -1)
    montant_i = cols.get("montant", -1)

    for n, row in enumerate(data_rows, start=2):
        def cell(i: int) -> str:
            return row[i].strip() if 0 <= i < len(row) else ""

        dt = _parse_date(cell(date_i))
        if dt is None:
            errors.append(f"Ligne {n} : date illisible « {cell(date_i)} » — ignorée.")
            continue

        credit = _parse_amount(cell(credit_i)) if credit_i >= 0 else None
        debit = _parse_amount(cell(debit_i)) if debit_i >= 0 else None
        montant = credit
        if montant is None and montant_i >= 0:
            raw_amount = _parse_amount(cell(montant_i))
            if raw_amount is not None:
                montant = raw_amount if raw_amount > 0 else None
        if montant is not None and debit is not None and debit > 0 and (credit is None or credit == 0):
            montant = None
        if montant is None or montant <= 0:
            if debit is not None and debit > 0:
                debits_ignored += 1
            elif montant_i >= 0 or credit_i >= 0:
                errors.append(f"Ligne {n} : montant crédit illisible « {cell(credit_i) or cell(montant_i)} » — ignorée.")
            continue

        libelle = cell(lib_i) or "Opération bancaire"
        reference = cell(ref_i)
        lines.append(BankLine(
            date=dt, libelle=libelle, montant=montant,
            reference=reference, row=n, extra_debit=debit or Decimal("0"),
        ))
    return lines, errors, debits_ignored


def bank_provider_ref(line: BankLine) -> str:
    """Référence unique et stable : BQ-<ref banque> ou hash de la ligne."""
    if line.reference:
        return f"BQ-{line.reference[:46]}"
    digest = hashlib.sha256(
        f"{line.date:%Y%m%d}|{line.libelle}|{line.montant}".encode("utf-8")
    ).hexdigest()[:12].upper()
    return f"BQ-{digest}"


@transaction.atomic
def reconcile_bank_statement(lines: list[BankLine], created_by, debits_ignored: int = 0,
                             errors: list[str] | None = None) -> BankReport:
    """
    Rapproche chaque ligne crédit du relevé avec les factures impayées,
    via la cascade de matching standard. Idempotent : une ligne déjà
    importée (provider_ref BQ-… existant) est ignorée sans erreur.
    """
    report = BankReport(total_lines=len(lines), debits_ignored=debits_ignored,
                        errors=errors or [])
    for line in lines:
        provider_ref = bank_provider_ref(line)
        if Payment.objects.filter(provider_ref=provider_ref).exists():
            report.skipped += 1
            report.details.append({
                "ref": provider_ref, "libelle": line.libelle,
                "montant": str(line.montant), "result": "Doublon — déjà importé",
                "status": "SKIP",
            })
            continue
        try:
            payment = Payment(
                provider_ref=provider_ref,
                amount=line.montant,
                channel=Channel.BANQUE,
                payer_name=line.libelle[:200],
                paid_at=line.date,
                raw_text=f"[BANQUE] Import relevé — {line.libelle}"
                         + (f" (réf. {line.reference})" if line.reference else ""),
                ai_confidence=1.0,
                created_by=created_by,
            )
            payment.save()
            new_status, invoice, method = match_payment(payment)
            payment.status = new_status
            payment.match_method = MatchMethod.AUTO_REF if invoice else method
            if invoice:
                payment.invoice = invoice
            payment.save(update_fields=["status", "match_method", "invoice", "updated_at"])

            report.imported += 1
            if new_status == PaymentStatus.RECONCILIE and method == MatchMethod.AUTO_REF:
                report.matched_ref += 1
                result = f"Rapproché par référence → {invoice.reference}"
                status = "REF"
            elif method == MatchMethod.AUTO_MONTANT:
                report.matched_amount += 1
                result = f"Rapproché par montant → {invoice.reference} (À VALIDER)"
                status = "MONTANT"
            elif method == MatchMethod.FUZZY:
                report.matched_fuzzy += 1
                result = f"Rapproché par similarité → {invoice.reference} (À VALIDER)"
                status = "FUZZY"
            else:
                report.non_rattaches += 1
                result = "Non rattaché — à traiter manuellement"
                status = "NON_RATTACHE"
            report.details.append({
                "ref": provider_ref, "libelle": line.libelle,
                "montant": str(line.montant), "result": result, "status": status,
            })
        except Exception as exc:  # jamais d'arrêt de tout l'import
            report.errors.append(f"Ligne {line.row} ({provider_ref}) : {exc}")
    return report
