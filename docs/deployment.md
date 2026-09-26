# Déploiement MoneXa

## Option 1 — Docker Compose (recommandé pour démo)

```bash
# Clone du repo
git clone https://github.com/Mafrix07/DEBUG.git monexa
cd monexa

# Configurer les variables d'environnement
cp backend/.env.example backend/.env
# Éditer backend/.env avec une SECRET_KEY aléatoire et DEBUG=False pour la prod

# Lancer les conteneurs (Backend Django + PostgreSQL)
docker-compose up --build -d

# Initialiser la base de données et les données de démo
docker-compose exec backend python manage.py migrate
docker-compose exec backend python manage.py seed_demo
```

Accès :
- Backend API : http://localhost:8000
- Swagger UI : http://localhost:8000/api/schema/swagger-ui/
- Django Admin : http://localhost:8000/admin/

## Option 2 — Backend local (Python)

```bash
cd backend

# Créer un venv
python -m venv venv
source venv/bin/activate  # Linux/Mac
# .\venv\Scripts\activate  # Windows

# Installer les dépendances
pip install -r requirements.txt

# Configurer l'environnement
cp .env.example .env
# Pour SQLite (tests), laisser DATABASE_URL vide
# Pour PostgreSQL, DATABASE_URL=postgres://user:pass@localhost:5432/monexa

# Appliquer les migrations
python manage.py migrate

# Charger les données de démonstration
python manage.py seed_demo

# Pré-calculer les prévisions Holt-Winters
python manage.py generate_forecast

# Lancer le serveur
python manage.py runserver 0.0.0.0:8000
```

## Option 3 — App mobile Flutter

```bash
cd mobile_app

# Installer les dépendances
flutter pub get

# Lancer sur un émulateur Android ou device physique
flutter run

# Pour pointer vers une API différente :
flutter run --dart-define=API_BASE_URL=http://192.168.1.10:8000
```

## Production — Render / Railway

Le backend est déployable sur Render ou Railway :

1. Créer un service Web Python pointant vers `backend/`
2. Build command : `pip install -r requirements.txt`
3. Start command : `gunicorn monexa_config.wsgi:application --bind 0.0.0.0:$PORT`
4. Add Postgres add-on (Render/Railway gère l'URL automatiquement dans `DATABASE_URL`)
5. Variables d'environnement :
   - `SECRET_KEY` (aléatoire)
   - `DEBUG=False`
   - `ALLOWED_HOSTS=*`
   - `DATABASE_URL` (auto-fourni par le add-on)
   - `CORS_ALLOWED_ORIGINS=https://monexa-app.vercel.app`
6. Post-deploy : `python manage.py migrate && python manage.py seed_demo`

## Option 4 — Railway (config prête dans le repo, 5 minutes)

Le dépôt contient tout ce qu'il faut : un `Dockerfile` racine (écoute sur `$PORT`,
migrate + seed_demo + collectstatic automatiques au démarrage) et un `railway.json`
(healthcheck `/login/`, restart ON_FAILURE). Aucune commande build/start à saisir.

### A. Via le dashboard (recommandé)

1. **railway.app** → `New Project` → `Deploy from GitHub repo` → `ErdisKodjo/MoneXa-V2` (branche `main`).
   Railway lit `railway.json` et build le `Dockerfile` racine automatiquement.
2. Une fois le service créé : `+ New` → `Database` → `Add PostgreSQL`.
   Railway injecte `DATABASE_URL` dans le service web (réseau privé).
3. Variables du service web (`Variables` → `New Variable`) :
   - `SECRET_KEY` = `python3 -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`
   - `DEBUG=False`
   - `CSRF_TRUSTED_ORIGINS=https://monexa-backend-production.up.railway.app` (adapter à l'URL générée à l'étape 4 ; redéploie auto)
   - `CORS_ALLOWED_ORIGINS=http://localhost:8080,http://127.0.0.1:8080`
   - `TREASORIA_USE_LLM=1` + `OPENAI_API_KEY` ou `GEMINI_API_KEY` (optionnel — fallback moteur de règles sinon)
4. `Settings` → `Networking` → `Generate Domain` → obtenir `https://<nom>.up.railway.app`.
5. Le déploie se relance : le healthcheck `/login/` passe au vert une fois
   `migrate + seed_demo + collectstatic + gunicorn` terminés (compte 2-4 min).

### B. Via la CLI (alternative)

```bash
npm i -g @railway/cli
railway login
railway init                       # dans le repo MoneXa
railway add --database postgresql  # plugin Postgres
railway variables set SECRET_KEY=... DEBUG=False \
  CSRF_TRUSTED_ORIGINS=https://monexa-backend-production.up.railway.app
railway up                         # build + deploy Dockerfile racine
railway domain                     # génère l'URL publique
```

### Vérifier Railway

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://<votre-app>.up.railway.app/login/   # 200
curl -s https://<votre-app>.up.railway.app/api/schema/swagger-ui/ | head -1          # Swagger UI
# Les comptes démo existent déjà (seed_demo) : gerant@monexa.tg / Monexa2026!
```

### Pièges Railway connus

- **403 sur le login web** : `CSRF_TRUSTED_ORIGINS` absente ou sans `https://` (schéma obligatoire).
- **Healthcheck KO puis OK** : le conteneur exécute migrate/seed avant gunicorn — c'est normal (2-4 min).
- **Build lent la 1re fois** : compilation psycopg2/Pillow — les builds suivants utilisent le cache.

### APK mobile pointant sur Railway

```bash
cd mobile_app
flutter build apk --release --dart-define=API_BASE_URL=https://<votre-app>.up.railway.app
# APK : build/app/outputs/flutter-apk/app-release.apk
```

## Vérifications post-déploiement

```bash
# Backend health check
curl https://your-app.onrender.com/api/schema/swagger-ui/  # doit afficher Swagger UI

# Auth test
curl -X POST https://your-app.onrender.com/api/auth/token/ \
  -H "Content-Type: application/json" \
  -d '{"email": "gerant@monexa.tg", "password": "Monexa2026!"}'

# Dashboard
curl https://your-app.onrender.com/api/dashboard/summary/ \
  -H "Authorization: Bearer <token>"

# Audit immuable — vérifier la chaîne
python manage.py shell -c "from auditing.services import verify_chain; print(verify_chain())"
```

## Plan B de démo (cahier des charges §16.3)

Si la démo live échoue :
1. Vidéo de secours 60s
2. Django Admin en back-office hors-ligne
3. seed_demo Docker local sur portable
