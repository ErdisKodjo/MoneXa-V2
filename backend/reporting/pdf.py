"""
Exports PDF (reportlab) — journal de caisse, bilan de trésorerie,
facture client avec QR code de paiement Mobile Money.

Ajout v2.1 au-delà du CSV : documents présentables pour la comptabilité
et la banque (charte MoneXa, en-tête, totaux, pied de page horodaté).
Ajout v2.3 : facture PDF prête à envoyer au client — QR code à scanner
pour payer via T-Money / Moov Money / Flooz (mode USSD, zéro intégration).
"""
from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

from django.utils import timezone as dj_tz
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from finance.models import Channel, Expense, ExpenseCategory, Payment

# Charte MoneXa
BRAND = colors.HexColor("#063082")
DARK = colors.HexColor("#1A2539")
GOLD = colors.HexColor("#F59E0B")
CREAM = colors.HexColor("#FFFBF4")
MUTED = colors.HexColor("#9DA9C3")
SUCCESS = colors.HexColor("#059669")
DANGER = colors.HexColor("#DC2626")

_BASE = getSampleStyleSheet()
S_TITLE = ParagraphStyle("mx_title", parent=_BASE["Title"], fontName="Helvetica-Bold",
                         fontSize=16, textColor=DARK, alignment=0)
S_SUB = ParagraphStyle("mx_sub", parent=_BASE["Normal"], fontName="Helvetica",
                       fontSize=9, textColor=MUTED, spaceAfter=6)
S_H2 = ParagraphStyle("mx_h2", parent=_BASE["Heading2"], fontName="Helvetica-Bold",
                      fontSize=11, textColor=BRAND, spaceBefore=10, spaceAfter=4)
S_TH = ParagraphStyle("mx_th", parent=_BASE["Normal"], fontName="Helvetica-Bold",
                      fontSize=8, textColor=colors.white)
S_TD = ParagraphStyle("mx_td", parent=_BASE["Normal"], fontName="Helvetica", fontSize=8)
S_RIGHT = ParagraphStyle("mx_right", parent=S_TD, alignment=2)
S_NOTE = ParagraphStyle("mx_note", parent=_BASE["Normal"], fontName="Helvetica-Oblique",
                        fontSize=8, textColor=MUTED, spaceBefore=8)

_TH_STYLE = TableStyle([
    ("BACKGROUND", (0, 0), (-1, 0), BRAND),
    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ("FONTSIZE", (0, 0), (-1, 0), 8),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, CREAM]),
    ("GRID", (0, 0), (-1, -1), 0.4, MUTED),
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("TOPPADDING", (0, 0), (-1, -1), 3),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
])

_MONEY_FMT = "{:,.0f}".format


def _fmt_fcfa(value) -> str:
    return f"{_MONEY_FMT(float(value)).replace(',', ' ')} FCFA"


def _stamp() -> str:
    return f"Généré le {dj_tz.localtime():%d/%m/%Y %H:%M} — MoneXa V2"


def journal_caisse_pdf(queryset) -> bytes:
    """Journal de caisse : tous les paiements, triés antéchronologique."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=12 * mm, rightMargin=12 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
        title="MoneXa — Journal de caisse", author="MoneXa",
    )
    total = sum(p.amount for p in queryset) if queryset else 0
    story = [
        Paragraph("Journal de caisse — MoneXa", S_TITLE),
        Paragraph(f"{queryset.count()} paiements · Total encaissé : {_fmt_fcfa(total)} · {_stamp()}", S_SUB),
    ]
    header = ["Date", "Référence", "Canal", "Payeur", "Téléphone", "Statut", "Méthode", "Montant"]
    rows = [header]
    for p in queryset.order_by("-paid_at"):
        rows.append([
            dj_tz.localtime(p.paid_at).strftime("%d/%m/%Y %H:%M"),
            p.provider_ref,
            p.get_channel_display(),
            p.payer_name or "—",
            p.payer_phone or "—",
            p.get_status_display(),
            p.get_match_method_display(),
            _fmt_fcfa(p.amount),
        ])
    table = Table(rows, colWidths=[30 * mm, 45 * mm, 25 * mm, 50 * mm, 30 * mm, 30 * mm, 35 * mm, 30 * mm], repeatRows=1)
    table.setStyle(_TH_STYLE)
    story += [table, Paragraph("Document généré automatiquement — vérifiable dans le journal d'audit immuable MoneXa.", S_NOTE)]
    doc.build(story)
    return buf.getvalue()


def bilan_pdf(days: int = 30) -> bytes:
    """
    Bilan de trésorerie sur N jours :
    encaissements par canal, dépenses par catégorie, solde net, alertes.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=16 * mm, rightMargin=16 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
        title="MoneXa — Bilan de trésorerie", author="MoneXa",
    )
    start = dj_tz.now() - timedelta(days=days)

    payments = list(Payment.objects.filter(paid_at__gte=start))
    expenses = list(Expense.objects.filter(paid_at__gte=start))
    enc_total = sum(p.amount for p in payments)
    dec_total = sum(e.amount for e in expenses)
    net = enc_total - dec_total

    story = [
        Paragraph("Bilan de trésorerie — MoneXa", S_TITLE),
        Paragraph(f"Période : {start:%d/%m/%Y} → {dj_tz.now():%d/%m/%Y} ({days} jours) · {_stamp()}", S_SUB),
        Paragraph("Synthèse", S_H2),
    ]
    synth = Table(
        [
            ["Total encaissé", "Total décaissé", "Solde net"],
            [
                _fmt_fcfa(enc_total),
                _fmt_fcfa(dec_total),
                _fmt_fcfa(net),
            ],
        ],
        colWidths=[58 * mm] * 3,
    )
    synth.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTSIZE", (0, 1), (-1, 1), 12),
        ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 1), (0, 1), SUCCESS),
        ("TEXTCOLOR", (1, 1), (1, 1), DANGER),
        ("TEXTCOLOR", (2, 1), (2, 1), SUCCESS if net >= 0 else DANGER),
        ("ALIGN", (0, 1), (-1, 1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.4, MUTED),
        ("TOPPADDING", (0, 1), (-1, 1), 8),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
    ]))
    story += [synth, Paragraph("Encaissements par canal", S_H2)]

    by_channel = {}
    for p in payments:
        by_channel[p.channel] = by_channel.get(p.channel, 0) + p.amount
    rows = [["Canal", "Montant", "Part"]]
    for code, value in sorted(by_channel.items(), key=lambda kv: -kv[1]):
        label = Channel(code).label if code in Channel.values else code
        share = f"{100 * float(value) / float(enc_total):.1f} %" if enc_total else "—"
        rows.append([label, _fmt_fcfa(value), share])
    if len(rows) == 1:
        rows.append(["Aucun encaissement sur la période", "—", "—"])
    t1 = Table(rows, colWidths=[80 * mm, 50 * mm, 30 * mm], repeatRows=1)
    t1.setStyle(_TH_STYLE)
    story.append(t1)

    story.append(Paragraph("Dépenses par catégorie", S_H2))
    by_cat = {}
    for e in expenses:
        by_cat[e.category] = by_cat.get(e.category, 0) + e.amount
    rows = [["Catégorie", "Montant", "Part"]]
    for code, value in sorted(by_cat.items(), key=lambda kv: -kv[1]):
        label = ExpenseCategory(code).label if code in ExpenseCategory.values else code
        share = f"{100 * float(value) / float(dec_total):.1f} %" if dec_total else "—"
        rows.append([label, _fmt_fcfa(value), share])
    if len(rows) == 1:
        rows.append(["Aucune dépense sur la période", "—", "—"])
    t2 = Table(rows, colWidths=[80 * mm, 50 * mm, 30 * mm], repeatRows=1)
    t2.setStyle(_TH_STYLE)
    story.append(t2)

    a_valider = Payment.objects.filter(status="A_VALIDER").count()
    anomalie = Payment.objects.filter(status="ANOMALIE").count()
    story += [
        Paragraph("Attention requise", S_H2),
        Paragraph(
            f"• Paiements en attente de validation comptable : <b>{a_valider}</b><br/>"
            f"• Paiements signalés en anomalie : <b>{anomalie}</b><br/>"
            f"• Fonds de roulement projeté : voir la prévision Holt-Winters (dashboard).",
            S_TD,
        ),
        Paragraph("Document présentable à la banque — totaux issus des écritures réconciliées MoneXa.", S_NOTE),
    ]
    doc.build(story)
    return buf.getvalue()


# ──────────────────────────────────────────────────────────────────────────
# Facture client PDF avec QR code de paiement (v2.3)
# ──────────────────────────────────────────────────────────────────────────

def _qr_payment_payload(invoice) -> str:
    """
    Contenu du QR code scannable par le client : référence, montant et
    codes USSD Mobile Money (Togo). Texte brut lisible par n'importe quel
    appareil photo — aucune intégration opérateur requise.
    """
    montant = _fmt_fcfa(invoice.amount)
    return (
        f"MoneXa — Paiement facture {invoice.reference}\n"
        f"Client : {invoice.client_name}\n"
        f"Montant : {montant}\n"
        f"T-Money : *880# (transfert vers le marchand MoneXa)\n"
        f"Moov Money : *155#\n"
        f"Flooz : *110#\n"
        f"Renseignez la référence {invoice.reference} dans le motif."
    )


def invoice_pdf(invoice) -> bytes:
    """
    Facture PDF prête à envoyer au client :
    en-tête MoneXa, coordonnées, montant, échéance, statut et QR code
    de paiement Mobile Money (T-Money / Moov / Flooz par USSD).
    """
    import qrcode  # import local : évite tout coût au chargement du module

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=18 * mm,
        title=f"MoneXa — Facture {invoice.reference}", author="MoneXa",
    )

    # QR code PNG en mémoire (aucun fichier disque)
    qr_img = qrcode.make(_qr_payment_payload(invoice), box_size=8, border=2)
    qr_buf = io.BytesIO()
    qr_img.save(qr_buf, format="PNG")
    qr_buf.seek(0)
    from reportlab.platypus import Image as RLImage
    qr = RLImage(qr_buf, width=48 * mm, height=48 * mm)

    overdue = (invoice.status == "EN_ATTENTE" and invoice.due_date < dj_tz.localdate())
    statut_label = invoice.get_status_display()
    if overdue:
        statut_label += " — EN RETARD"

    info_rows = [
        ["Référence", "Client", "Téléphone"],
        [
            Paragraph(f"<b>{invoice.reference}</b>", S_TD),
            Paragraph(f"<b>{invoice.client_name}</b>", S_TD),
            invoice.client_phone or "—",
        ],
        ["Émise le", "Échéance", "Statut"],
        [
            invoice.issue_date.strftime("%d/%m/%Y"),
            Paragraph(
                f"<b>{invoice.due_date.strftime('%d/%m/%Y')}</b>"
                + (" <font color='#DC2626'>(retard)</font>" if overdue else ""),
                S_TD,
            ),
            Paragraph(
                f"<font color='#DC2626'>{statut_label}</font>" if overdue else statut_label,
                S_TD,
            ),
        ],
    ]
    info = Table(info_rows, colWidths=[56 * mm, 56 * mm, 58 * mm])
    info.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("BACKGROUND", (0, 2), (-1, 2), CREAM),
        ("TEXTCOLOR", (0, 2), (-1, 2), DARK),
        ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
        ("FONTSIZE", (0, 2), (-1, 2), 8),
        ("GRID", (0, 0), (-1, -1), 0.4, MUTED),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))

    total = Table(
        [["TOTAL À PAYER"], [Paragraph(f"<b>{_fmt_fcfa(invoice.amount)}</b>", ParagraphStyle("mx_total", parent=_BASE["Title"], fontSize=18, textColor=BRAND))]],
        colWidths=[170 * mm],
    )
    total.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), DARK),
        ("TEXTCOLOR", (0, 0), (0, 0), colors.white),
        ("FONTNAME", (0, 0), (0, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (0, 0), 10),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("BOX", (0, 0), (-1, -1), 0.8, BRAND),
        ("TOPPADDING", (0, 1), (0, 1), 6),
        ("BOTTOMPADDING", (0, 1), (0, 1), 8),
    ]))

    story = [
        Paragraph(f"Facture {invoice.reference}", S_TITLE),
        Paragraph(f"MoneXa — Votre trésorerie centralisée · {_stamp()}", S_SUB),
        Spacer(1, 6 * mm),
        info,
        Spacer(1, 8 * mm),
        total,
        Spacer(1, 8 * mm),
        Paragraph("Paiement Mobile Money — scannez ce QR code", S_H2),
        qr,
        Paragraph(
            "Le client compose le code USSD de son opérateur (T-Money *880#, "
            "Moov Money *155#, Flooz *110#), transfère le montant exact et "
            f"mentionne la référence <b>{invoice.reference}</b> dans le motif. "
            "Le SMS de confirmation est automatiquement réconcilié par l'IA MoneXa.",
            S_NOTE,
        ),
        Paragraph("Document généré par MoneXa — traçable dans le journal d'audit immuable.", S_NOTE),
    ]
    doc.build(story)
    return buf.getvalue()
