# MoneXa — Image Docker « root » pour Railway / tout PaaS à $PORT.
# Contexte de build : racine du repo (le backend/Dockerfile reste pour docker-compose).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=monexa_config.settings

WORKDIR /app

# Déps système pour Pillow + psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev libjpeg-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ /app/

EXPOSE 8000

# Railway injecte $PORT (fallback 8000 pour un docker run local).
# Whitenoise sert les statics MVT ; seed_demo est idempotent (démo live prête).
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py seed_demo && python manage.py collectstatic --noinput --clear && gunicorn monexa_config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 3 --timeout 60 --access-logfile -"]
