<div align="center">

# MoneXa 🪙 — CFO virtuel pour PME ouest-africaines

**Plateforme intelligente de trésorerie** : extraction IA des reçus Mobile Money, réconciliation automatique, audit immuable SHA-256, chatbot TresorIA.

> **V2 — Django MVT fonctionnel et non démo** : une interface web complète rendue côté serveur
> (9 écrans : login, dashboard KPIs, factures, paiements, dépenses, anomalies, audit immuable,
> TresorIA, exports) complète l'API REST et l'app mobile. Voir [`docs/ANALYSE_V2.md`](docs/ANALYSE_V2.md).

Hackathon **ESIG Tech Arena 2026** — Défi 2 (Application Mobile) — 25 au 27 septembre 2026

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://python.org)
[![Django](https://img.shields.io/badge/Django-4.2-092E20?logo=django&logoColor=white)](https://djangoproject.com)
[![DRF](https://img.shields.io/badge/DRF-3.15-A30000?logo=django&logoColor=white)](https://django-rest-framework.org)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791?logo=postgresql&logoColor=white)](https://postgresql.org)
[![Flutter](https://img.shields.io/badge/Flutter-3.22-02569B?logo=flutter&logoColor=white)](https://flutter.dev)
[![Backend CI](https://github.com/ErdisKodjo/MoneXa-V2/actions/workflows/backend.yml/badge.svg)](https://github.com/ErdisKodjo/MoneXa-V2/actions/workflows/backend.yml)
[![Mobile CI](https://github.com/ErdisKodjo/MoneXa-V2/actions/workflows/mobile.yml/badge.svg)](https://github.com/ErdisKodjo/MoneXa-V2/actions/workflows/mobile.yml)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

</div>

---

## 🎯 Aperçu

En Afrique de l'Ouest, les PME réalisent l'essentiel de leurs encaissements via **Mobile Money** (**T-Money**, **Moov Money**, **Flooz**). Pourtant :
- La **réconciliation** entre les SMS de confirmation et les factures émises est manuelle et chronophage.
- Les **erreurs de caisse**, **fraudes internes** et **doublons** de transaction passent inaperçus.
- La **connectivité réseau** instable pénalise la saisie sur le terrain.
- La **projection du fonds de roulement** relève souvent de l'improvisation.

**MoneXa** résout ces problématiques en s'appuyant sur trois piliers :
1. 🤖 **Automatisation par IA** — extraction LLM multimodale des reçus, matching automatique, détection d'anomalies
2. 💎 **Rigueur financière** — PostgreSQL ACID, DecimalField, contraintes UNIQUE, audit immuable hash-chainé
3. 📱 **Accessibilité mobile** — Flutter offline-first, trilingue (FR / Ewé / Kabyé)

> **Pitch en une phrase** : *MoneXa est un CFO virtuel pour PME ouest-africaines : il photographie vos reçus mobile money, l'IA extrait et réconcilie automatiquement les paiements avec vos factures, vous alerte sur les anomalies, et vous donne une vision claire de votre trésorerie à 30 jours — accessible depuis votre téléphone, sans connexion permanente.*

---

## 📑 Sommaire

1. [Stack technique](#-stack-technique)
2. [Structure du dépôt](#-structure-du-dépôt)
3. [Fonctionnalités principales](#-fonctionnalités-principales)
4. [Architecture](#-architecture)
5. [Installation & Démarrage](#-installation--démarrage)
6. [Comptes de test](#-comptes-de-test)
7. [Documentation de l'API](#-documentation-de-lapi)
8. [Tests](#-tests)
9. [Palette de couleurs](#-palette-de-couleurs)
10. [Roadmap](#-roadmap-post-hackathon)
11. [Équipe & Contact](#-équipe--contact)

---

## 🛠 Stack technique

| Composant | Technologie | Justification |
| :--- | :--- | :--- |
| **Backend** | Python 3.12 · Django 4.2 LTS · DRF 3.15 | Admin intégré, ORM mature, écosystème unifié avec l'IA |
| **Base de données** | PostgreSQL 16 (SQLite pour tests) | ACID natif, DecimalField, triggers d'audit |
| **Auth** | simplejwt + django-otp (2FA TOTP) | JWT pour Flutter, sessions pour Admin, 2FA Gérant |
| **Documentation API** | drf-spectacular (OpenAPI 3) | Schéma auto-généré, Swagger UI gratuit |
| **IA multimodale** | GPT-4o-mini Vision / Gemini Flash + Pydantic v2 | Robustesse photos floues, validation stricte |
| **Data Science** | statsmodels (Holt-Winters) · scikit-learn (Isolation Forest) | Prévisions J+7/J+30, détection d'anomalies |
| **App mobile** | Flutter 3.22+ (Dart) · flutter_bloc · Hive | Performance native, offline-first, single codebase |
| **Back-office** | Django Admin + HTMX + TailwindCSS | Gain 6-8h, plan B démo hors-ligne |
| **Audit** | Hash-chaining SHA-256 (Python pur) | Détection active de falsification, démontrable en live |
| **i18n** | Django i18n + ARB Flutter | FR + Ewé + Kabyé nativement supportés |
| **Déploiement** | Docker Compose · Render/Railway-ready | Setup local 1 commande, prod conteneurisée |

> **Note de compatibilité** : Django 5.x exige DRF ≥ 3.16 (qui requiert à son tour Django ≥ 5.0). Pour éviter cette circularité en contexte hackathon, nous utilisons Django 4.2 LTS + DRF 3.15 — compatibles et stables. Le code est 100% compatible Django 5 (il suffit d'upgrader DRF à 3.16+ en production).

---

## 📁 Structure du dépôt

```
MoneXa-V2/
├── README.md                       # Ce fichier
├── docker-compose.yml              # Django + PostgreSQL
├── .github/workflows/              # CI : backend (pytest) + mobile (analyze/test)
│
├── backend/                        # Backend Django + DRF + MVT
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── .env.example
│   ├── manage.py
│   ├── pytest.ini
│   ├── conftest.py                 # Fixtures pytest partagées
│   ├── monexa_config/              # Settings, URLs, WSGI/ASGI
│   ├── accounts/                   # Custom User + RBAC + JWT
│   ├── finance/                    # Account, Invoice, Payment, Expense + services IA
│   ├── auditing/                   # AuditLog immuable SHA-256
│   ├── reporting/                  # KPIs, exports, dashboard
│   ├── assistant/                  # TresorIA chatbot
│   ├── webui/                      # V2 — couche MVT (views, forms, urls, mixins RBAC)
│   ├── templates/webui/            # V2 — 12 templates (login, dashboard, paiements…)
│   ├── static/css/monexa.css       # V2 — design system MoneXa (charte officielle)
│   └── docs/                       # (placeholder)
│
├── mobile_app/                     # App Flutter (Clean Architecture + BLoC)
│   ├── pubspec.yaml
│   ├── README.md
│   ├── analysis_options.yaml
│   └── lib/
│       ├── main.dart
│       ├── core/                   # Theme, network, router, l10n (FR/Ewé/Kabyé)
│       ├── features/               # auth, dashboard, upload_evidence, payments, profile
│       └── shared/                 # widgets, utils
│
└── docs/                           # Documentation projet
    ├── ANALYSE_V2.md               # V2 — audit complet + axes d'amélioration
    ├── architecture.md
    ├── rbac-matrix.md
    ├── design-system.md
    ├── deployment.md
    └── api-reference.md
```

---

## ⚡ Fonctionnalités principales

- 📸 **Extraction multimodale de preuves** — Photographiez un reçu ou un écran SMS, l'IA extrait instantanément la référence opérateur, le montant, la date et le payeur (Pydantic validation). **V2.1 : 3 niveaux — LLM Vision → OCR Tesseract local + parser SMS déterministe → mock ; 100 % hors-ligne possible.**
- 🔗 **Cascade de réconciliation automatique** — Matching intelligent à 4 niveaux : référence exacte → montant + date sous 7j → fuzzy payeur → file `A_VALIDER`.
- 💰 **Encaissement direct Mobile Money (V2.1)** — Push de collecte T-Money / Moov / Flooz vers le client, webhook opérateur signé HMAC, conversion automatique en paiement réconcilié + audit.
- 🛡️ **Audit immuable cryptographique** — Journalisation hash-chainée SHA-256. Toute altération en base brise la chaîne d'intégrité, détectable via `verify_chain()`.
- 💬 **TresorIA** — Chatbot CFO en langage naturel. Alimenté par 15 KPIs pré-calculés. **Jamais** de SQL direct généré par le LLM.
- 📈 **Prévisions de trésorerie J+7 et J+30** — Lissage exponentiel triple (Holt-Winters) sur 90 jours d'historique, intervalle de confiance à 80%. **V2.1 : saisonnalité « jours de marché » calibrée sur l'historique.**
- 🚨 **Détection d'anomalies hybride** — Règles déterministes (doublon, écart montant, hors fenêtre, paiement nocturne) + scoring ML Isolation Forest. **V2.1 : scan anti-fraude SMS (numéros usurpés, références falsifiées, rafales, hameçonnage).**
- 🔐 **2FA TOTP côté web (V2.1)** — Activation par QR code pour le Gérant, connexion en deux étapes, anti-replay.
- 🔔 **Notifications in-app (V2.1)** — Rappels de factures échues et file de validation, commande `send_reminders` cron-able.
- 📱 **Mobile Offline-First & trilingue** — Cache Hive, sync différée, interface **Français / Ewé / Kabyé**. **V2.1 : file de sync offline Hive — un reçu photographié sans réseau part automatiquement au retour du réseau.**
- 📄 **Exports SYSCOHADA, CSV & PDF (V2.1)** — Journal de caisse et bilan de trésorerie PDF présentables (charte MoneXa), CSV Excel.

---

## 🏗 Architecture

Voir [`docs/architecture.md`](docs/architecture.md) pour le diagramme complet.

```
[Clients : App web MVT (desktop) + Flutter mobile + Django Admin] 
        │ Session (CSRF) / JWT / Session
        ▼
[Django 4.2 LTS + DRF + WebUI MVT]  ── [Services IA internes : ai_pipeline, matcher, anomalies, forecast]
        │                              └── [Audit immuable SHA-256]
        ▼
[PostgreSQL 16 ACID]
```

3 décisions structurantes dès H0 :
1. Custom User AVANT la première migration (règle n°1 Django)
2. API pur DRF **+ couche MVT web fonctionnelle (V2)**, Django Admin conservé comme back-office technique
3. Services IA internes (pas de microservice séparé en 48h)

### Écrans web MVT (V2)

| Écran | Route | Rôle minimum |
|---|---|---|
| Connexion (sessions, CSRF) | `/login/` | public |
| Vérification 2FA TOTP | `/login/totp/` | public (compte 2FA) |
| Dashboard KPIs + graphes CSS | `/dashboard/` | connecté |
| Factures (liste, filtres, création) | `/factures/` | connecté (scoping caissier) |
| Paiements (upload preuve IA, SMS, validation) | `/paiements/` | connecté (validation : comptable+) |
| Encaissements Mobile Money (collecte) | `/encaissements/` | comptable+ |
| Dépenses (liste, création) | `/depenses/` | connecté (scoping caissier) |
| Notifications (cloche, rappels) | `/notifications/` | connecté |
| Anomalies (règles + fraude SMS + Isolation Forest) | `/anomalies/` | gérant |
| Journal d'audit immuable + verify_chain | `/audit/` | gérant |
| Sécurité (2FA TOTP, pipeline IA) | `/securite/` | gérant |
| TresorIA chatbot | `/assistant/` | connecté |
| Exports CSV + PDF | `/exports/` | comptable+ |

---

## 🚀 Installation & Démarrage

### Option 1 : Docker Compose (recommandé)

```bash
git clone https://github.com/Mafrix07/DEBUG.git monexa
cd monexa
cp backend/.env.example backend/.env
docker-compose up --build -d
docker-compose exec backend python manage.py migrate
docker-compose exec backend python manage.py seed_demo
```

Accès :
- **App web MVT** : http://localhost:8000 → redirige vers le login, puis le dashboard
- Backend API : http://localhost:8000/api/
- Swagger UI : http://localhost:8000/api/schema/swagger-ui/
- Django Admin : http://localhost:8000/admin/

### Option 2 : Backend local (Python)

```bash
cd backend
python -m venv venv
source venv/bin/activate    # Linux/Mac  |  .\venv\Scripts\activate  (Windows)
pip install -r requirements.txt
cp .env.example .env

python manage.py migrate
python manage.py seed_demo
python manage.py generate_forecast
python manage.py runserver 0.0.0.0:8000
```

### Option 3 : App mobile Flutter

```bash
cd mobile_app
flutter pub get
flutter run
# Pour pointer vers une API différente :
flutter run --dart-define=API_BASE_URL=http://192.168.1.10:8000
```

---

## 👥 Comptes de test

Après `python manage.py seed_demo` :

| Rôle | Email | Mot de passe | Accès |
|---|---|---|---|
| **Gérant** | `gerant@monexa.tg` | `Monexa2026!` | Full + 2FA optionnel |
| **Comptable** | `comptable@monexa.tg` | `Monexa2026!` | Validation, reporting |
| **Caissier** | `caissier@monexa.tg` | `Monexa2026!` | Saisie mobile terrain |

Voir la matrice RBAC complète dans [`docs/rbac-matrix.md`](docs/rbac-matrix.md).

---

## 📖 Documentation de l'API

Une fois le backend démarré :
- **Swagger UI** : http://localhost:8000/api/schema/swagger-ui/
- **Schéma OpenAPI brut** : http://localhost:8000/api/schema/
- **Redoc** : http://localhost:8000/api/schema/redoc/

Voir [`docs/api-reference.md`](docs/api-reference.md) pour la liste complète des endpoints avec exemples.

---

## 🧪 Tests

```bash
cd backend
pytest                            # Tous les tests
pytest -v                         # Verbose
pytest auditing/tests/            # Tests du journal immuable uniquement
pytest --cov=. --cov-report=term  # Coverage
```

**40 tests pytest-django** couvrent :
- ✅ **RBAC** : permissions par rôle (Caissier / Comptable / Gérant)
- ✅ **Audit immuable** : `save()` et `delete()` lèvent `PermissionError`, `verify_chain()` détecte les cassures
- ✅ **Matcher** : 4 niveaux de cascade (AUTO_REF, AUTO_MONTANT, FUZZY, NON_RATTACHE)
- ✅ **IA pipeline** : extraction déterministe, validation Pydantic (montants négatifs, opérateurs inconnus rejetés)
- ✅ **Anomalies** : règles (écart montant, sans facture, hors fenêtre, nocturne)
- ✅ **KPIs** : compute_kpis retourne les 15 KPIs attendus
- ✅ **TresorIA** : pattern-matching, fallback, throttle, authentification

---

## 🎨 Palette de couleurs

Extraite du fichier `code couleur.jpeg` fourni avec le cahier des charges.

| Couleur | Hex | Usage |
|---|---|---|
| Bleu indigo profond | `#063082` | Primary — confiance fintech |
| Marine foncé | `#1A2539` | Texte, autorité |
| Crème chaud | `#FFFBF4` | Background, chaleur |
| Or | `#F59E0B` | CTA, Mobile Money |
| Vert émeraude | `#059669` | Succès, validation |
| Rouge | `#DC2626` | Anomalies, erreur |
| Gris-bleu | `#9DA9C3` | Muted, secondary |

Voir [`docs/design-system.md`](docs/design-system.md) pour la charte complète.

---

## 🗺 Roadmap post-hackathon

### Tier 1 — Court terme (1–3 mois)
- Connecteurs agrégateurs (CinetPay, Flutterwave) pour ingestion automatique SMS
- Import de relevés bancaires CSV
- Celery + Redis pour les traitements batch
- Sentry monitoring + Grafana supervision
- Tests E2E Playwright + Flutter integration_test
- 2FA imposé pour tous les rôles en production
- Conformité RGPD renforcée (rétention raw_text 90 jours)

### Tier 2 — Moyen terme (3–6 mois)
- Module Dépenses & Fournisseurs complet + catégorisation IA
- Exports SYSCOHADA complets (journal, balance, compte de résultat)
- Fermeture de caisse espèces anti-fraude
- ✅ **Factures PDF avec QR code de paiement T-Money/Moov (V2.3)** — `/factures/<id>/pdf/`, codes USSD *880# / *155# / *110#, marquage EN RETARD automatique
- ✅ **Rappels automatiques LLM pour factures impayées > 7 jours (V2.3)** — `send_reminders` rédige les relances (LLM si clé API, template sinon), anti-spam, `--dry-run`
- ✅ **Scoring de fiabilité clients (V2.3)** — score 0–100 (règlement, ponctualité, impayés, anomalies) affiché sur le dashboard
- ✅ **Rapport hebdomadaire LLM (CFO virtuel, V2.3)** — `generate_weekly_report` : chiffres pré-calculés + rédaction LLM, livré en notification aux Gérants
- PWA offline-first pour caissier
- Notifications WhatsApp Business

### Tier 3 — Long terme (6–18 mois)
- Multi-boutiques / multi-guichets
- Apple Wallet / Google Wallet
- Marketplace de services financiers
- Prévision de saisonnalité avancée (12 mois)
- Détection de fraude avancée (autoencodeurs)
- Module de paie OHADA
- API publique (open banking)
- Mode multi-devise (FCFA, €, $)
- Assistant vocal multilingue (Ewé, Kabyé, FR)
- Extension régionale (Sénégal, CI, Burkina, Mali)

---

## 👨‍💻 Équipe & Contact

Projet réalisé pour l'**ESIG Tech Arena 2026** par l'équipe **MoneXa**.

- **Défi** : Défi 2 — Application Mobile
- **Contact** : `team.monexa@esig.example`
- **Dépôt Git** : https://github.com/ErdisKodjo/MoneXa-V2
- **Cahier des charges** : `ESIG_Tech_Arena_2026_Cahier_des_charges.pdf` (32 pages, inclus dans ce dépôt)
