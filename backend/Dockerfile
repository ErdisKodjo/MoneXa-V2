FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=monexa_config.settings

WORKDIR /app

# Install system deps for Pillow + psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev libjpeg-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Production-ready : migrate + seed + collectstatic + gunicorn (whitenoise sert le CSS MVT)
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py seed_demo && python manage.py collectstatic --noinput --clear && gunicorn monexa_config.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 60 --access-logfile -"]
