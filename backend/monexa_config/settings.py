"""
Django settings for MoneXa — Fintech Treasury Platform.

Configuration conforme au cahier des charges ESIG Tech Arena 2026 (Défi 2).
Production : PostgreSQL 16. Tests locaux : SQLite fallback automatique.
"""
from pathlib import Path
from decouple import Config, RepositoryEnv, Csv
import os

BASE_DIR = Path(__file__).resolve().parent.parent
# Lire UNIQUEMENT le .env du backend (ignore les .env globaux du sandbox)
_env_file = BASE_DIR / ".env"
config = Config(RepositoryEnv(str(_env_file))) if _env_file.exists() else Config(os.environ)

# ──────────────────────────────────────────────────────────────────────────
# Sécurité
# ──────────────────────────────────────────────────────────────────────────
SECRET_KEY = config("SECRET_KEY", default="dev-insecure-key-change-me-in-prod")
DEBUG = config("DEBUG", default=False, cast=bool)
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="*", cast=Csv())

# ──────────────────────────────────────────────────────────────────────────
# Applications
# ──────────────────────────────────────────────────────────────────────────
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # 3rd-party
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "drf_spectacular",
    "corsheaders",
    "django_filters",
    "django_otp",
    "django_otp.plugins.otp_totp",

    # Local
    "accounts",
    "finance",
    "auditing",
    "reporting",
    "assistant",
    "webui",  # Couche MVT fonctionnelle (vues render + templates + forms)
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # Static files en prod (pas de nginx requis)
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "monexa_config.urls"

# Auth web MVT (sessions) — redirections login/logout
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/dashboard/"
LOGOUT_REDIRECT_URL = "/login/"
WSGI_APPLICATION = "monexa_config.wsgi.application"
ASGI_APPLICATION = "monexa_config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "webui.context_processors.notifications",
            ],
        },
    },
]

# ──────────────────────────────────────────────────────────────────────────
# Base de données — PostgreSQL 16 en prod, SQLite en tests
# ──────────────────────────────────────────────────────────────────────────
DATABASE_URL = config("DATABASE_URL", default="").strip()
if DATABASE_URL and DATABASE_URL.startswith(("postgres://", "postgresql://", "postgres://", "sqlite:")):
    # Production PostgreSQL (ou sqlite explicite)
    import dj_database_url  # type: ignore
    DATABASES = {"default": dj_database_url.parse(DATABASE_URL)}
else:
    # Tests locaux SQLite — fallback automatique
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# ──────────────────────────────────────────────────────────────────────────
# Authentification — Custom User MoneXa
# ──────────────────────────────────────────────────────────────────────────
AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ──────────────────────────────────────────────────────────────────────────
# Internationalisation — FR + Ewé + Kabyé
# ──────────────────────────────────────────────────────────────────────────
LANGUAGE_CODE = config("LANGUAGE_CODE", default="fr")
TIME_ZONE = config("TIME_ZONE", default="Africa/Lome")
USE_I18N = True
USE_TZ = True

LANGUAGES = [
    ("fr", "Français"),
    ("ee", "Ewé"),
    ("kab", "Kabyé"),
]

LOCALE_PATHS = [BASE_DIR / "locale"]

# ──────────────────────────────────────────────────────────────────────────
# Fichiers statiques & médias
# ──────────────────────────────────────────────────────────────────────────
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]  # CSS design system webui (css/monexa.css)
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ──────────────────────────────────────────────────────────────────────────
# Django REST Framework
# ──────────────────────────────────────────────────────────────────────────
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",  # pour Django Admin
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.UserRateThrottle",
        "rest_framework.throttling.AnonRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "user": "60/min",
        "anon": "20/min",
        "assistant": "10/min",
    },
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ),
}

SPECTACULAR_SETTINGS = {
    "TITLE": "MoneXa API",
    "DESCRIPTION": (
        "Plateforme intelligente de trésorerie pour PME ouest-africaines. "
        "Extraction IA multimodale des reçus Mobile Money, réconciliation "
        "automatique, audit immuable SHA-256, chatbot TresorIA.\n\n"
        "ESIG Tech Arena 2026 — Défi 2 — Application Mobile."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
}

# ──────────────────────────────────────────────────────────────────────────
# SimpleJWT
# ──────────────────────────────────────────────────────────────────────────
from datetime import timedelta  # noqa: E402

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(
        minutes=config("JWT_ACCESS_MINUTES", default=15, cast=int)
    ),
    "REFRESH_TOKEN_LIFETIME": timedelta(
        days=config("JWT_REFRESH_DAYS", default=7, cast=int)
    ),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# ──────────────────────────────────────────────────────────────────────────
# CORS
# ──────────────────────────────────────────────────────────────────────────
CORS_ALLOWED_ORIGINS = config(
    "CORS_ALLOWED_ORIGINS",
    default="http://localhost:8080,http://127.0.0.1:8080,http://localhost:8000,http://127.0.0.1:8000",
    cast=Csv(),
)
CORS_ALLOW_ALL_ORIGINS = DEBUG

# ──────────────────────────────────────────────────────────────────────────
# IA — Gemini / OpenAI Vision (optionnel)
# ──────────────────────────────────────────────────────────────────────────
OPENAI_API_KEY = config("OPENAI_API_KEY", default="")
GEMINI_API_KEY = config("GEMINI_API_KEY", default="")
GEMINI_VISION_MODEL = config("GEMINI_VISION_MODEL", default="gemini-2.0-flash")
OPENAI_VISION_MODEL = config("OPENAI_VISION_MODEL", default="gpt-4o-mini")

# TresorIA (chatbot CFO) — LLM réel si clé API, sinon moteur de règles.
# Le LLM ne reçoit JAMAIS d'accès DB : uniquement les KPIs pré-calculés (§12.1).
TREASORIA_USE_LLM = config("TREASORIA_USE_LLM", default="1")
TREASORIA_LLM_TIMEOUT = config("TREASORIA_LLM_TIMEOUT", default="12")

# ──────────────────────────────────────────────────────────────────────────
# Trésorerie — saisonnalité & passerelles Mobile Money
# ──────────────────────────────────────────────────────────────────────────
# Jours de marché boostés dans les prévisions (0=lundi … 6=dimanche).
# Défaut « 5 » = grand marché du samedi, typique des PME ouest-africaines.
MARKET_DAYS = config("MARKET_DAYS", default="5")

# Préfixes opérateurs Togo (+228) — détection fraude « numéro usurpé »
MONEXA_OPERATOR_PREFIXES = {
    "TMONEY": ("90", "91", "92", "93"),   # Togocom / T-Money
    "MOOV": ("94", "95"),                 # Moov Money
    "FLOOZ": ("96", "97"),                # Flooz
}

# Passerelles de collecte Mobile Money (sandbox si non configuré)
TMONEY_COLLECTION_URL = config("TMONEY_COLLECTION_URL", default="")
TMONEY_API_KEY = config("TMONEY_API_KEY", default="")
TMONEY_API_SECRET = config("TMONEY_API_SECRET", default="")
MOOV_COLLECTION_URL = config("MOOV_COLLECTION_URL", default="")
MOOV_API_KEY = config("MOOV_API_KEY", default="")
MOOV_API_SECRET = config("MOOV_API_SECRET", default="")
FLOOZ_COLLECTION_URL = config("FLOOZ_COLLECTION_URL", default="")
FLOOZ_API_KEY = config("FLOOZ_API_KEY", default="")
FLOOZ_API_SECRET = config("FLOOZ_API_SECRET", default="")
GATEWAY_WEBHOOK_SECRET = config("GATEWAY_WEBHOOK_SECRET", default="change-me-webhook-secret")

# ──────────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────────
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "loggers": {
        "monexa": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "monexa.ai": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
