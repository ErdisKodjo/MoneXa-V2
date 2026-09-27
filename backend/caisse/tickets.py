"""
Tickets de caisse — cahier des charges §5.3 (POS-05).

Trois formats depuis la même source de vérité (la vente) :
1. ticket_texte()        — rendu texte 58 mm (32 col) ou 80 mm (48 col),
                           lisible sur n'importe quelle imprimante thermique.
2. ticket_escpos_bytes() — flux binaire ESC/POS (init, centrage, gras,
                           QR code USSD T-Money/Moov/Flooz, coupe papier)
                           prêt à envoyer au port USB/Bluetooth.
3. ticket_pdf()          — PDF exactement au format du rouleau (58/80 mm)
                           pour partage WhatsApp/e-mail et repli universel.

Le QR code réutilise les codes USSD togolais existants : *880# T-Money,
*155# Moov, *110# Flooz — le client peut payer une prochaine fois en
scannant (boucle facturation-encaissement §5.5).
"""
from __future__ import annotations

import io
from decimal import Decimal

from django.utils import timezone

from .models import MoyenPaiement, Vente

LARGEURS = {58: 32, 80: 48}  # colonnes de caractères par largeur de rouleau

# Codes USSD togolais (boucle facturation-encaissement §5.5, réutilisés POS)
USSD_CODES = {"TMONEY": "*880#", "MOOV": "*155#", "FLOOZ": "*110#"}

MENUS_LÉGALES = (
    "Merci de votre visite !\n"
    "Téléphone paiement : *880# T-Money / *155# Moov / *110# Flooz\n"
)


def _fmt_fcfa(v: Decimal) -> str:
    return f"{v:,.0f}".replace(",", " ")


def _ussd_string(vente: Vente) -> str:
    """Chaîne encodée dans le QR — premier USSD togolais disponible."""
    code = USSD_CODES.get("TMONEY", "*880#")
    return f"Paiement MoneXa {vente.reference} — {code}"


# ──────────────────────────────────────────────────────────────────────────
# 1. Rendu texte
# ──────────────────────────────────────────────────────────────────────────
def ticket_texte(vente: Vente, largeur_mm: int = 58) -> str:
    cols = LARGEURS.get(largeur_mm, 32)
    out: list[str] = []
    center = lambda s: s.center(cols).rstrip()  # noqa: E731
    line = lambda c="─": c * cols  # noqa: E731
    duo = lambda g, d: (g[: cols - len(d) - 1]).ljust(cols - len(d) - 1) + d.rjust(len(d))  # noqa: E731

    out.append(center("MoneXa"))
    out.append(center("REÇU DE VENTE"))
    out.append(line())
    out.append(duo("Réf. :", vente.reference))
    out.append(duo("Date :", timezone.localtime(vente.created_at).strftime("%d/%m/%Y %H:%M")))
    out.append(duo("Vendeur :", vente.vendeur.display_name[:20]))
    if vente.client_name:
        out.append(duo("Client :", vente.client_name[:20]))
    out.append(line())
    for l in vente.lignes.all():
        out.append(l.designation[:cols])
        detail = f"{l.quantite:n} x {_fmt_fcfa(l.prix_unitaire_ttc)}"
        if l.remise_pct:
            detail += f" (-{l.remise_pct:n}%)"
        out.append(duo(detail, _fmt_fcfa(l.total_ttc)))
    out.append(line())
    if vente.remise_panier:
        out.append(duo("Remise panier", f"-{vente.remise_panier:n}%"))
    out.append(duo("TOTAL TTC", f"{_fmt_fcfa(vente.total_ttc)} FCFA"))
    out.append(duo("dont TVA", _fmt_fcfa(vente.total_tva)))
    out.append(line())
    for p in vente.paiements.all():
        out.append(duo(p.get_moyen_display(), _fmt_fcfa(p.montant)))
        if p.reference:
            out.append(f"  Tx : {p.reference}")
    if vente.rendu:
        out.append(duo("Rendu", _fmt_fcfa(vente.rendu)))
    out.append(line())
    out.append(center("Merci de votre visite !"))
    if not vente.ticket_imprime:
        out.append(center("(copie — file d'impression)"))
    out.append("Scannez pour payer :")
    out.append(_ussd_string(vente))
    out.append(center("MoneXa — votre CFO virtuel"))
    return "\n".join(out)


# ──────────────────────────────────────────────────────────────────────────
# 2. Flux ESC/POS binaire
# ──────────────────────────────────────────────────────────────────────────
ESC = b"\x1b"
GS = b"\x1d"


def _escpos_center(text: str) -> bytes:
    return ESC + b"a\x01" + text.encode("cp437", errors="replace") + b"\n"


def _escpos_left(text: str) -> bytes:
    return ESC + b"a\x00" + text.encode("cp437", errors="replace") + b"\n"


def _escpos_bold(text: str) -> bytes:
    return ESC + b"E\x01" + text.encode("cp437", errors="replace") + ESC + b"E\x00\n"


def _escpos_big(text: str) -> bytes:
    return ESC + b"a\x01" + ESC + b"!\x30" + text.encode("cp437", errors="replace") + \
        ESC + b"!\x00" + b"\n"


def _escpos_qr(data: str) -> bytes:
    """QR code ESC/POS standard (modèle 2, taille 6, corréction M)."""
    payload = data.encode("utf-8")
    n = len(payload) + 3
    store = GS + b"(k\x04\x00\x31\x50\x30" + bytes([n]) + payload
    print_cmd = GS + b"(k\x03\x00\x31\x51\x30"
    model = GS + b"(k\x04\x00\x31\x41\x32\x00"  # modèle 2
    size = GS + b"(k\x03\x00\x31\x43\x06"       # module 6
    err = GS + b"(k\x03\x00\x31\x45\x31"        # erreur niveau M
    return model + size + err + store + print_cmd


def _escpos_cut() -> bytes:
    return GS + b"V\x42\x00"  # coupe partielle


def ticket_escpos_bytes(vente: Vente, largeur_mm: int = 58) -> bytes:
    """Flux ESC/POS complet : init → ticket → QR USSD → coupe."""
    text = ticket_texte(vente, largeur_mm)
    out = bytearray()
    out += ESC + b"@\x1b" + b"t\x0b"  # init + codepage CP850 (accents)
    for raw in text.split("\n"):
        stripped = raw.strip()
        if stripped in ("MoneXa",):
            out += _escpos_big(stripped)
        elif stripped in ("REÇU DE VENTE", "TOTAL TTC") or stripped.startswith("TOTAL TTC"):
            out += _escpos_bold(raw.rstrip())
        elif stripped == "─" * LARGEURS.get(largeur_mm, 32):
            out += _escpos_left("─" * LARGEURS.get(largeur_mm, 32))
        else:
            out += _escpos_left(raw.rstrip())
    out += b"\n"
    out += _escpos_qr(_ussd_string(vente))
    out += b"\n"
    out += _escpos_cut()
    return bytes(out)


# ──────────────────────────────────────────────────────────────────────────
# 3. PDF au format rouleau
# ──────────────────────────────────────────────────────────────────────────
def ticket_pdf(vente: Vente, largeur_mm: int = 58) -> bytes:
    """PDF exactement à la taille du rouleau (58 ou 80 mm), via reportlab."""
    from reportlab.lib.pagesizes import mm
    from reportlab.pdfgen import canvas as rl_canvas

    text = ticket_texte(vente, largeur_mm)
    lines = text.split("\n")
    line_h = 3.6 * mm if largeur_mm == 80 else 3.4 * mm
    margin = 4 * mm
    width = largeur_mm * mm
    height = margin * 2 + line_h * len(lines) + 26 * mm  # + QR
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(width, height))
    from reportlab.lib.colors import HexColor

    dark = HexColor("#1A2539")
    brand = HexColor("#063082")
    y = height - margin
    c.setFont("Courier-Bold", 10 if largeur_mm == 80 else 9)
    for ln in lines:
        stripped = ln.strip()
        if stripped == "MoneXa":
            c.setFillColor(brand)
            c.setFont("Helvetica-Bold", 12)
            c.drawCentredString(width / 2, y, "MoneXa")
            c.setFont("Courier", 9)
        elif "TOTAL TTC" in stripped or stripped == "REÇU DE VENTE":
            c.setFillColor(dark)
            c.setFont("Courier-Bold", 9)
            c.drawString(margin, y, ln)
            c.setFont("Courier", 9)
        else:
            c.setFillColor(dark)
            c.drawString(margin, y, ln)
        y -= line_h
    # QR code USSD
    try:
        from reportlab.graphics.barcode.qr import QrCodeWidget
        from reportlab.graphics.shapes import Drawing
        from reportlab.graphics import renderPDF

        qr = QrCodeWidget(_ussd_string(vente))
        size = 18 * mm
        b = qr.getBounds()
        d = Drawing(size, size, transform=[size / (b[2] - b[0]), 0, 0, size / (b[3] - b[1]), 0, 0])
        d.add(qr)
        renderPDF.draw(d, c, (width - size) / 2, y - size + 2 * mm)
    except Exception:
        pass
    c.showPage()
    c.save()
    return buf.getvalue()
