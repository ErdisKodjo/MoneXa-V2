# 🔍 ANALYSE V2 — MoneXa vs Cahier des charges « Django MVT fonctionnel, non démo »

> Audit technique réalisé le 2026-09-25 — objectif : transformer MoneXa d'un prototype API + Admin
> en une **application Django MVT fonctionnelle** prête pour la date de déploiement.

---

## 1. Méthodologie d'audit

L'audit a été conduit en quatre passes, du général au détail, sur le dépôt cloné
`https://github.com/Mafrix07/MoneXa.git` :

1. **Inventaire statique** — arborescence complète backend (5 apps Django) et mobile (Flutter, Clean Architecture + BLoC), lecture des documents projet (`docs/architecture.md`, `docs/rbac-matrix.md`, `docs/design-system.md`, `docs/deployment.md`, `Reste.txt`).
2. **Vérification d'exécution réelle** — création d'un environnement virtuel Python 3.12, installation de `requirements.txt`, exécution des migrations, du `seed_demo`, des **40 tests pytest** (résultat : **40/40 verts**) et démarrage du serveur avec smoke tests HTTP (root, JWT, dashboard API, `/login/` web).
3. **Confrontation au cahier des charges** — le livrable attendu est une application **Django MVT fonctionnelle et non démo** : Model (OK), View (templates + forms rendus côté serveur), Template (interface web complète), et non un simple catalogue d'endpoints REST doublé d'un Django Admin brut.
4. **Revue de l'app mobile** — lecture statique des écrans, blocs, repositories, client réseau, configuration l10n et manifest PWA (le SDK Flutter n'étant pas disponible dans l'environnement d'audit, la validation s'est limitée à une revue de code).

## 2. Ce qui est déjà fonctionnel (à conserver tel quel)

Le socle backend est de qualité professionnelle et ne nécessite **aucune refonte**. Les points
suivants ont été vérifiés par exécution, pas seulement par lecture de code.

| Domaine | Constat vérifié | Statut |
|---|---|---|
| Modèles financiers | `DecimalField(14,2)` partout, `provider_ref` unique anti-doublon, index `(status, paid_at)` et `(channel, paid_at)` | ✅ Solide |
| RBAC | 3 rôles hiérarchisés (Gérant > Comptable > Caissier), helpers `is_comptable_or_higher()`, permissions DRF réutilisables | ✅ Solide |
| Tests | `pytest` : 40/40 verts en 5,5 s (RBAC, audit immuable, matcher 4 niveaux, pipeline IA, anomalies, KPIs, TresorIA) | ✅ Vert |
| Réconciliation | Cascade 4 niveaux : référence exacte → montant+7j → fuzzy payeur → `A_VALIDER` | ✅ Solide |
| Audit immuable | Hash-chain SHA-256, `save()`/`delete()` verrouillés, `verify_chain()` détecte toute falsification | ✅ Solide |
| Prévisions | Holt-Winters J+7/J+30 avec cache `ForecastCache` et intervalle de confiance 80 % | ✅ Fonctionnel |
| API REST | JWT rotation + blacklist, throttling 60/min, OpenAPI 3 auto-générée (drf-spectacular) | ✅ Fonctionnel |
| Pipeline IA | Extraction LLM multimodale avec fallback déterministe hors-ligne, validation Pydantic stricte | ✅ Fonctionnel |
| Docker | `docker-compose.yml` Django + PostgreSQL 16, `Dockerfile` backend présent | ✅ Prêt |
| App mobile | 5 écrans (login, dashboard, upload preuve, paiements, profil), BLoC, refresh token interceptor, Hive offline, trilingue ARB | ⚠️ Bon socle, finitions manquantes |

## 3. Écart majeur : la couche MVT est inexistante

C'est **le** point de non-conformité au cahier des charges. Les constats suivants ont été
reproduits en conditions réelles (serveur démarré, requêtes curl) :

| # | Constat | Preuve |
|---|---|---|
| 1 | Le dossier `backend/templates/` configuré dans `settings.TEMPLATES` **n'existe pas** | `ls templates/` → introuvable |
| 2 | **Aucune vue Django classique** (`render()`), aucun `Form` Django dans tout le backend | 0 occurrence de `django.forms` / `TemplateView` |
| 3 | La racine `/` redirige vers **Swagger UI** (documentation API), pas vers une application | `curl /` → 302 → `/api/schema/swagger-ui/` |
| 4 | `/login/` web renvoie **404** — aucun formulaire de connexion MVT | `curl /login/` → 404 |
| 5 | Le « back-office web » promis (README : *Admin + HTMX + TailwindCSS*) est un **Django Admin brut** sans personnalisation | Aucun fichier HTMX/Tailwind dans le dépôt |
| 6 | Aucune interface web pour : valider les paiements `A_VALIDER`, résoudre les anomalies, consulter le journal d'audit, discuter avec TresorIA, télécharger les exports | Ces flux n'existent que via l'API JSON |

**Conséquence** : en l'état, un évaluateur qui ouvre `http://host:8000/` voit une page de
documentation d'API. Le projet donne l'impression d'une démo, précisément ce que le cahier des
charges exclut. La valeur métier (KPIs, réconciliation, audit, IA) est invisible hors Swagger et
hors de l'app mobile Flutter, qui exige un smartphone pour la démonstration.

## 4. Axes d'amélioration recencés (priorisés)

### 🔴 P1 — Construire la couche MVT fonctionnelle (blocant déploiement)

- **A1. Application Django `webui`** : vues basées sur classes + mixins RBAC réutilisant les helpers
  existants (`ComptableRequiredMixin`, `GerantRequiredMixin`), formulaires Django natifs avec
  validation serveur (`InvoiceForm`, `ExpenseForm`, `PaymentSmsForm`), URLs nommées à la racine.
- **A2. Templates renderés côté serveur** : `login`, `dashboard` (KPIs + graphes CSS sans
  dépendance JS), `factures` (liste + création), `paiements` (liste, filtres statut/canal,
  upload de preuve IA, saisie SMS manuelle, validation comptable), `dépenses` (liste + création),
  `anomalies` (règles + Isolation Forest), `audit` (journal hash-chainé + `verify_chain()`),
  `TresorIA` (chat par POST, historique en session), `exports` (téléchargements CSV).
- **A3. Design system conforme** : palette officielle `#063082 / #1A2539 / #FFFBF4 / #F59E0B /
  #059669 / #DC2626 / #9DA9C3`, typographie Plus Jakarta Sans + Inter, composants cards 16 px,
  boutons CTA or, badges de statut colorés — fidèles à `docs/design-system.md`.
- **A4. RBAC côté web** : caissier limité à ses objets et aux écrans de saisie ; comptable +
  validation et exports ; gérant seul sur anomalies et audit. Navigation adaptative selon rôle.
- **A5. Messages flash + CSRF** : `django.contrib.messages` sur chaque action POST, protection
  CSRF native sur tous les formulaires, redirections propres après action.

### 🟠 P2 — Finitions app mobile (avant démo terrain)

- **A6. Manifest PWA personnalisé** : remplacer le manifest Flutter générique (nom `monexa`,
  description « A new Flutter project », couleur `#0175C2`) par la charte MoneXa
  (`#063082`, description réelle).
- **A7. CI GitHub Actions** : workflow backend (pytest sur SQLite) + workflow mobile
  (`flutter analyze` + `flutter test`) déclenchés à chaque push — verrou qualité avant la deadline.
- **A8. Hygiène de dépôt** : `.gitignore` racine (venvs, `db.sqlite3`, `staticfiles`, `.env`),
  suppression du bruit build si présent, badge CI.

### 🟡 P3 — Robustesse i18n et documentation

- **A9. i18n web** : chaînes des templates passées par `{% trans %}` avec catalogues
  FR complet + EE/Kabyé amorcés (alignés sur l'app mobile trilingue).
- **A10. Documentation V2** : `README.md` mis à jour (arborescence réelle, écrans web,
  comptes de test, instructions de déploiement), le présent `ANALYSE_V2.md`.

## 5. Plan d'exécution V2 (réalisé dans ce dépôt)

| Étape | Livrable | Résultat |
|---|---|---|
| 1 | App `webui` (views, forms, urls, mixins) | 9 écrans MVT rendus côté serveur |
| 2 | Templates + CSS design system MoneXa | Interface fidèle à la charte, responsive |
| 3 | Tests régression backend + smoke tests web | 40 tests API verts + parcours web vérifiés |
| 4 | Manifest PWA + CI + .gitignore | Mobile et qualité verrouillés |
| 5 | Push `MoneXa-V2` | Dépôt distant à jour |

## 6. Risques résiduels et recommandations post-déploiement

1. **PostgreSQL en production** : le fallback SQLite est pratique pour la démo, mais la
   contrainte `unique` anti-doublon et les triggers d'audit n'ont leur pleine garantie
   transactionnelle que sur PostgreSQL — brancher `DATABASE_URL` avant la mise en ligne.
2. **Clé IA optionnelle** : le pipeline fonctionne en mode déterministe sans clé ; fournir
   `GEMINI_API_KEY` ou `OPENAI_API_KEY` activera l'extraction réelle des photos de reçus.
3. **Rotation du token GitHub** : tout token utilisé pour un push doit être révoqué et
   régénéré immédiatement après l'opération.
4. **2FA** : imposer le TOTP pour le rôle Gérant en production (déjà supporté par le modèle).
