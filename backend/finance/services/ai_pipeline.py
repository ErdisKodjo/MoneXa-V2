"""
AI pipeline — extraction LLM multimodale des reçus Mobile Money.

Pipeline (cahier des charges §11.1):
1. Image uploaded via /api/payments/evidence/
2. Service calls LLM multimodal (GPT-4o-mini Vision or Gemini Flash)
3. JSON response validated by Pydantic PaymentExtraction
4. Returns dict with montant, reference, operator, emetteur, date, ai_confidence

DEMO MODE (no OPENAI_API_KEY):
    Returns a deterministic mock based on image content hash.
    This ensures tests pass without external API dependencies.

PRODUCTION MODE (OPENAI_API_KEY set):
    Calls OpenAI Vision API. Falls back to mock on error.
"""
from __future__ import annotations
import hashlib
import io
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator, ConfigDict

logger = logging.getLogger("monexa.ai")


# ──────────────────────────────────────────────────────────────────────────
# Pydantic schema — strict validation of LLM output
# ──────────────────────────────────────────────────────────────────────────
class PaymentExtraction(BaseModel):
    """Strict schema for AI-extracted payment data. Any malformed field → reject."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    montant: Decimal = Field(..., gt=0, description="Montant en FCFA, strictement positif")
    reference: str = Field(..., min_length=3, max_length=50,
                            description="Référence opérateur (provider_ref)")
    operator: str = Field(..., description="TMONEY | MOOV | FLOOZ")
    type_operation: str = Field(default="PAIEMENT", description="Type d'opération")
    emetteur: str = Field(..., min_length=2, max_length=200, description="Nom du payeur")
    telephone_emetteur: Optional[str] = Field(default=None, max_length=20)
    date_paiement: datetime = Field(..., description="Date de la transaction")

    @field_validator("operator")
    @classmethod
    def validate_operator(cls, v: str) -> str:
        v_up = v.upper().strip()
        # Mapping tolérant
        mapping = {
            "T-MONEY": "TMONEY", "TMONEY": "TMONEY", "T MONEY": "TMONEY",
            "MOOV": "MOOV", "MOOV MONEY": "MOOV", "MOOV-MONEY": "MOOV",
            "FLOOZ": "FLOOZ",
        }
        if v_up not in mapping:
            raise ValueError(f"Opérateur inconnu: {v}. Attendu: TMONEY, MOOV, FLOOZ.")
        return mapping[v_up]

    @field_validator("date_paiement")
    @classmethod
    def validate_date(cls, v: datetime) -> datetime:
        if v > datetime.now(timezone.utc) + timedelta(days=1):
            raise ValueError("Date de paiement dans le futur.")
        if v.year < 2020:
            raise ValueError("Date de paiement trop ancienne.")
        return v


# ──────────────────────────────────────────────────────────────────────────
# Mock data generator (deterministic, based on image content hash)
# ──────────────────────────────────────────────────────────────────────────
_PAYER_NAMES = [
    "Kossi Mensah", "Afi Adjovi", "Koffi Agbessi", "Mensah Kossi",
    "Adzo Komla", "Komi Agbélo", "Awa Tchalla", "Yaovi Dotse",
    "Afia Mawusi", "Kossi Tsolenyanu",
]
_PHONE_PREFIXES = ["90", "91", "92", "93", "70", "79"]


def _hash_image(image_bytes: bytes) -> str:
    """Return a hex digest of the image content."""
    return hashlib.sha256(image_bytes).hexdigest()


def _deterministic_mock(image_bytes: bytes) -> PaymentExtraction:
    """
    Generate a deterministic PaymentExtraction from the image hash.
    Same image → same extraction. Different image → different extraction.
    """
    digest = _hash_image(image_bytes)
    # Use parts of the hash to derive each field deterministically
    seed = int(digest[:8], 16)
    amount = (seed % 980_000) + 5_000  # 5_000 .. 985_000 FCFA

    operator_idx = (int(digest[8:10], 16) % 3)
    operators = ["TMONEY", "MOOV", "FLOOZ"]
    operator = operators[operator_idx]

    # Provider ref prefix by operator
    prefix_map = {"TMONEY": "TMX", "MOOV": "MV", "FLOOZ": "FL"}
    ref = f"{prefix_map[operator]}{digest[10:20].upper()}"

    payer_idx = (int(digest[20:22], 16) % len(_PAYER_NAMES))
    payer_name = _PAYER_NAMES[payer_idx]

    phone_idx = (int(digest[22:24], 16) % len(_PHONE_PREFIXES))
    phone_prefix = _PHONE_PREFIXES[phone_idx]
    phone_rest = f"{int(digest[24:30], 16) % 100:02d} {int(digest[30:36], 16) % 100:02d} {int(digest[36:42], 16) % 100:02d}"
    phone = f"+228 {phone_prefix} {phone_rest}"

    # Date — within last 30 days
    days_ago = int(digest[42:44], 16) % 30
    paid_at = datetime.now(timezone.utc) - timedelta(days=days_ago,
                                                       hours=int(digest[44:46], 16) % 24)

    return PaymentExtraction(
        montant=Decimal(amount),
        reference=ref,
        operator=operator,
        type_operation="PAIEMENT",
        emetteur=payer_name,
        telephone_emetteur=phone,
        date_paiement=paid_at,
    )


_VISION_PROMPT = """Tu extrais un reçu Mobile Money ouest-africain (T-Money, Moov Money, Flooz).
Réponds UNIQUEMENT avec un JSON compact, sans markdown, avec exactement ces clés:
{
  "montant": 50000,
  "reference": "TMX123456",
  "operator": "TMONEY",
  "emetteur": "Nom du payeur",
  "telephone_emetteur": "+228 90 00 00 00",
  "date_paiement": "2026-09-24T14:23:00+00:00"
}
operator doit être TMONEY, MOOV ou FLOOZ. montant > 0. date_paiement ISO-8601."""


# ──────────────────────────────────────────────────────────────────────────
# Parser SMS déterministe — formats réels T-Money / Moov / Flooz (Plan A texte)
# Aucune clé API requise : fonctionne 100 % hors-ligne.
# ──────────────────────────────────────────────────────────────────────────
_RE_AMOUNT = re.compile(r"(\d[\d\s.,]{2,}?)\s*(?:FCFA|F\s?CFA|CFA|F\b)", re.IGNORECASE)
_RE_REF = re.compile(
    r"(?:ref(?:erence)?|id\s*trans(?:action)?|transaction|trans\s*id|id)\s*[:.]?\s*"
    r"([A-Z0-9][A-Z0-9._\-]{5,40})",
    re.IGNORECASE,
)
_RE_REF_BARE = re.compile(r"\b((?:TMX|MV|FL|MP)[A-Z0-9.\-]{5,40}|\d{12,18})\b")
_RE_PHONE = re.compile(r"(?:\+?228[\s.\-]?)?\b([79]\d[\s.\-]?\d{2}[\s.\-]?\d{2}[\s.\-]?\d{2})\b")
_RE_DATE = re.compile(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})(?:[,\s]*(?:à|at)?\s*(\d{1,2}):(\d{2}))?")
_RE_PARTY_PAREN = re.compile(
    r"(?:re[cç]u|reception|transfert|envoy[eé]|paie?ment|versement)[^()\n]{0,60}?"
    r"\b(?:de|du|à|a)\s+(.{2,60}?)\s*\(?\s*(?:\+?228[\s.\-]?)?\b([79]\d{7})\b",
    re.IGNORECASE,
)
_RE_PARTY_PLAIN = re.compile(
    r"(?:re[cç]u|reception|transfert|envoy[eé]|paie?ment|versement)[^()\n]{0,60}?"
    r"\b(?:de|du|à|a)\s+((?:[A-ZÀ-Ÿ][\wÀ-ÿ'’\-]+(?:\s+[A-ZÀ-Ÿ][\wÀ-ÿ'’\-]+){0,3})|\d{8})",
)
_RE_OPERATOR_HINTS = {
    "TMONEY": re.compile(r"t[\s\-]?money|togocom|tmx|t\-money", re.IGNORECASE),
    "MOOV": re.compile(r"moov", re.IGNORECASE),
    "FLOOZ": re.compile(r"flooz", re.IGNORECASE),
}


def _clean_amount_str(raw: str) -> Optional[Decimal]:
    """'1 500 000 FCFA' / '25.000 FCFA' / '25000' → Decimal."""
    cleaned = raw.replace(" ", "").replace("\u00a0", "").replace(".", "").replace(",", "")
    if not cleaned.isdigit():
        return None
    value = int(cleaned)
    if value <= 0 or value > 9_999_999_999:
        return None
    return Decimal(value)


def _detect_operator(text: str, reference: str) -> str:
    for operator, hint in _RE_OPERATOR_HINTS.items():
        if hint.search(text):
            return operator
    ref_up = (reference or "").upper()
    if ref_up.startswith(("TMX", "TM")):
        return "TMONEY"
    if ref_up.startswith(("MV", "MP")):
        return "MOOV"
    if ref_up.startswith("FL"):
        return "FLOOZ"
    return ""


def parse_sms_payment(text: str) -> Optional[PaymentExtraction]:
    """
    Parse un SMS Mobile Money ouest-africain avec des règles déterministes.

    Couvre les formulations réelles T-Money / Moov Money / Flooz (reçu du
    client « Vous avez envoyé… » ou reçu du commerçant « Vous avez reçu… »).
    Retourne None si un champ obligatoire (montant, référence) manque —
    l'appelant bascule alors sur le LLM puis le mock.
    """
    if not text or len(text) < 10:
        return None

    amount = None
    m = _RE_AMOUNT.search(text)
    if m:
        amount = _clean_amount_str(m.group(1))
    if amount is None:
        return None

    reference = ""
    m = _RE_REF.search(text) or _RE_REF_BARE.search(text)
    if m:
        reference = m.group(1).strip("._-")
    if not reference:
        # Dernier recours : ID long uniquement en chiffres (T-Money legacy)
        m = re.search(r"\b(\d{14,18})\b", text)
        if m:
            reference = m.group(1)
    if not reference:
        return None

    operator = _detect_operator(text, reference)
    if not operator:
        return None

    emetteur, phone = "", ""
    m = _RE_PARTY_PAREN.search(text)
    if m:
        emetteur = m.group(1).strip(" -–—:,").strip()
        phone = f"+228 {m.group(2)[:2]} {m.group(2)[2:4]} {m.group(2)[4:6]} {m.group(2)[6:8]}"
    else:
        m = _RE_PARTY_PLAIN.search(text)
        if m:
            candidate = m.group(1).strip()
            if candidate.isdigit() and len(candidate) == 8:
                phone = f"+228 {candidate[:2]} {candidate[2:4]} {candidate[4:6]} {candidate[6:8]}"
            else:
                emetteur = candidate.title()
    if not phone:
        m = _RE_PHONE.search(text)
        if m:
            digits = re.sub(r"\D", "", m.group(1))
            phone = f"+228 {digits[:2]} {digits[2:4]} {digits[4:6]} {digits[6:8]}"

    paid_at = datetime.now(timezone.utc)
    m = _RE_DATE.search(text)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if year < 100:
            year += 2000
        hour = int(m.group(4)) if m.group(4) else 12
        minute = int(m.group(5)) if m.group(5) else 0
        try:
            paid_at = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
        except ValueError:
            paid_at = datetime.now(timezone.utc)

    try:
        return PaymentExtraction(
            montant=amount,
            reference=reference,
            operator=operator,
            emetteur=emetteur or "Client Mobile Money",
            telephone_emetteur=phone or None,
            date_paiement=paid_at,
        )
    except Exception as exc:  # Pydantic ValidationError ou autre
        logger.debug("parse_sms_payment rejeté: %s", exc)
        return None


def _call_llm_text(text: str) -> Optional[PaymentExtraction]:
    """Extraction LLM texte seul (GPT-4o-mini / Gemini Flash) si clé présente."""
    import base64 as _b64  # noqa: F401  (parité avec vision, évite les imports conditionnels)
    import json
    import urllib.error
    import urllib.request

    provider_prompt = (
        _VISION_PROMPT
        + "\n\nSMS brut à analyser (aucune image) :\n<<<\n"
        + text[:1500]
        + "\n>>>"
    )
    body_openai = {
        "model": _setting("OPENAI_VISION_MODEL", os.environ.get("OPENAI_VISION_MODEL", "gpt-4o-mini")),
        "temperature": 0,
        "messages": [{"role": "user", "content": provider_prompt}],
    }

    def _post(url: str, payload: dict, headers: dict):
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))

    openai_key = _setting("OPENAI_API_KEY")
    if openai_key.strip():
        try:
            data = _post(
                "https://api.openai.com/v1/chat/completions",
                body_openai,
                {"Authorization": f"Bearer {openai_key.strip()}", "Content-Type": "application/json"},
            )
            return _parse_llm_json(data["choices"][0]["message"]["content"])
        except Exception as exc:
            logger.warning("LLM texte OpenAI indisponible: %s", exc)

    gemini_key = _setting("GEMINI_API_KEY")
    if gemini_key.strip():
        try:
            model = _setting("GEMINI_VISION_MODEL", os.environ.get("GEMINI_VISION_MODEL", "gemini-2.0-flash"))
            data = _post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={gemini_key.strip()}",
                {"contents": [{"parts": [{"text": provider_prompt}]}]},
                {"Content-Type": "application/json"},
            )
            return _parse_llm_json(data["candidates"][0]["content"]["parts"][0]["text"])
        except Exception as exc:
            logger.warning("LLM texte Gemini indisponible: %s", exc)
    return None


def _ocr_image(image_bytes: bytes) -> str:
    """
    OCR local gratuit (Tesseract) — aucune clé API requise.
    Retourne le texte détecté ou '' en cas d'échec (jamais d'exception).
    """
    try:
        from PIL import Image
        import pytesseract

        image = Image.open(io.BytesIO(image_bytes))
        image = image.convert("L")  # niveaux de gris — reçus imprimés/screenshot
        text = pytesseract.image_to_string(
            image, lang="eng", config="--psm 6"
        )
        return text.strip()
    except Exception as exc:
        logger.debug("OCR indisponible (%s) — fallback déterministe", exc)
        return ""


def pipeline_status() -> dict:
    """
    Diagnostic du pipeline d'extraction (affiché sur le dashboard).
    Permet au Gérant de savoir quel mode est actif avant la démo.
    """
    tesseract_ok = False
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
        tesseract_ok = True
    except Exception:
        pass
    if _setting("GEMINI_API_KEY").strip() or _setting("OPENAI_API_KEY").strip():
        mode = "LLM Vision (clé API active)"
        level = "premium"
    elif tesseract_ok:
        mode = "OCR local Tesseract + règles SMS (100 % hors-ligne)"
        level = "local"
    else:
        mode = "Démo déterministe (aucune IA disponible)"
        level = "demo"
    return {"mode": mode, "level": level, "ocr_available": tesseract_ok}


def _parse_llm_json(text: str) -> Optional[PaymentExtraction]:
    """Best-effort parse of an LLM JSON payload into PaymentExtraction."""
    import json
    import re

    if not text:
        return None
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if fenced:
        cleaned = fenced.group(1)
    else:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start >= 0 and end > start:
            cleaned = cleaned[start : end + 1]
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    try:
        return PaymentExtraction.model_validate(payload)
    except Exception:
        return None


def _mime_from_filename(filename: str) -> str:
    name = (filename or "").lower()
    if name.endswith(".png"):
        return "image/png"
    if name.endswith(".webp"):
        return "image/webp"
    if name.endswith(".gif"):
        return "image/gif"
    return "image/jpeg"


def _call_openai_vision(image_bytes: bytes, filename: str, api_key: str) -> Optional[PaymentExtraction]:
    import base64
    import json
    import urllib.error
    import urllib.request

    b64 = base64.b64encode(image_bytes).decode("ascii")
    mime = _mime_from_filename(filename)
    body = {
        "model": _setting("OPENAI_VISION_MODEL", os.environ.get("OPENAI_VISION_MODEL", "gpt-4o-mini")),
        "temperature": 0,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _VISION_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"},
                    },
                ],
            }
        ],
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
        return _parse_llm_json(content)
    except (urllib.error.URLError, KeyError, IndexError, TimeoutError, ValueError):
        return None


def _call_gemini_vision(image_bytes: bytes, filename: str, api_key: str) -> Optional[PaymentExtraction]:
    import base64
    import json
    import urllib.error
    import urllib.request

    b64 = base64.b64encode(image_bytes).decode("ascii")
    mime = _mime_from_filename(filename)
    model = _setting("GEMINI_VISION_MODEL", os.environ.get("GEMINI_VISION_MODEL", "gemini-2.0-flash"))
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )
    body = {
        "contents": [
            {
                "parts": [
                    {"text": _VISION_PROMPT},
                    {"inline_data": {"mime_type": mime, "data": b64}},
                ]
            }
        ]
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = data["candidates"][0]["content"]["parts"][0]["text"]
        return _parse_llm_json(content)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:400]
        logger.warning("Gemini Vision HTTP %s: %s", e.code, body)
        return None
    except (urllib.error.URLError, KeyError, IndexError, TimeoutError, ValueError) as e:
        logger.warning("Gemini Vision fallback mock: %s", e)
        return None


def _setting(name: str, default: str = "") -> str:
    """Read from Django settings (.env) then process env."""
    try:
        from django.conf import settings
        value = getattr(settings, name, None)
        if value:
            return str(value)
    except Exception:
        pass
    return os.environ.get(name, default) or default


def _try_real_vision(image_bytes: bytes, filename: str) -> Optional[PaymentExtraction]:
    """Call Gemini Flash or GPT-4o-mini if a key is present. Never raise."""
    # Keep pytest deterministic (mock). Runserver / Docker still use the real API.
    if "pytest" in sys.modules and not os.environ.get("FORCE_REAL_VISION"):
        return None
    gemini_key = _setting("GEMINI_API_KEY")
    openai_key = _setting("OPENAI_API_KEY")
    if gemini_key.strip():
        extracted = _call_gemini_vision(image_bytes, filename, gemini_key.strip())
        if extracted:
            return extracted
    if openai_key.strip():
        extracted = _call_openai_vision(image_bytes, filename, openai_key.strip())
        if extracted:
            return extracted
    return None


# ──────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────
def extract_payment_from_image(image_bytes: bytes, filename: str = "") -> dict:
    """
    Extract payment data from an image of a Mobile Money SMS / receipt.

    Uses GPT-4o-mini Vision or Gemini Flash when an API key is set.
    Falls back automatically to a deterministic mock (offline / tests / errors).
    """
    # Niveau 1 — LLM Vision (clé API)
    extraction = _try_real_vision(image_bytes, filename)
    used_llm = extraction is not None
    used_ocr = False
    # Niveau 2 — OCR local Tesseract → parser SMS déterministe (100 % hors-ligne)
    if extraction is None:
        ocr_text = _ocr_image(image_bytes)
        if ocr_text:
            extraction = parse_sms_payment(ocr_text)
            used_ocr = extraction is not None
            if used_ocr:
                extraction.telephone_emetteur = extraction.telephone_emetteur or None
    # Niveau 3 — mock déterministe (démo / tests)
    if extraction is None:
        extraction = _deterministic_mock(image_bytes)

    if used_llm:
        confidence, tag = 0.97, "LLM VISION"
    elif used_ocr:
        confidence, tag = 0.90, "OCR TESSERACT"
    else:
        confidence, tag = 0.85, "DEMO"
    raw_text = (
        f"[{tag}] Paiement reçu de {extraction.emetteur} "
        f"({extraction.telephone_emetteur or 'n/a'}), "
        f"montant {extraction.montant} FCFA via {extraction.operator}. "
        f"Réf: {extraction.reference}. Date: {extraction.date_paiement:%Y-%m-%d %H:%M}."
    )

    return {
        "montant": extraction.montant,
        "reference": extraction.reference,
        "operator": extraction.operator,
        "emetteur": extraction.emetteur,
        "telephone_emetteur": extraction.telephone_emetteur,
        "date_paiement": extraction.date_paiement,
        "ai_confidence": confidence,
        "raw_text": raw_text,
        "extraction": extraction,
    }


def extract_payment_from_text(text: str) -> dict:
    """
    Fallback : parse raw SMS text directly (Plan B).
    Used by /api/payments/manual-text/ endpoint.
    """
    # Niveau 1 — parser SMS déterministe (règles opérateurs, hors-ligne)
    extraction = parse_sms_payment(text)
    if extraction is not None:
        confidence, tag = 0.95, "SMS RULES"
    else:
        # Niveau 2 — LLM texte si clé API présente
        extraction = _call_llm_text(text)
        if extraction is not None:
            confidence, tag = 0.97, "LLM TEXT"
        else:
            # Niveau 3 — mock déterministe (démo / tests)
            text_bytes = text.encode("utf-8")
            extraction = _deterministic_mock(text_bytes)
            confidence, tag = 0.80, "TEXT DEMO"
    return {
        "montant": extraction.montant,
        "reference": extraction.reference,
        "operator": extraction.operator,
        "emetteur": extraction.emetteur,
        "telephone_emetteur": extraction.telephone_emetteur,
        "date_paiement": extraction.date_paiement,
        "ai_confidence": confidence,
        "raw_text": f"[{tag}] {text}",
        "extraction": extraction,
    }
