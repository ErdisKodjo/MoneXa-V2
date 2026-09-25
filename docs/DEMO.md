# 🎬 MoneXa — Guide de démonstration (ESIG Tech Arena 2026)

> Parcours recommandé : 5 minutes, trois rôles, un pipeline complet
> « facture → encaissement Mobile Money → réconciliation IA → audit immuable ».

## 0. Préparation (avant l'arrivée du jury)

```bash
# Backend — deux options
docker compose up -d                       # PostgreSQL 16 + Django (prod-like)
# ou
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate && python manage.py seed_demo
python manage.py runserver                 # http://localhost:8000

# Rappels de notifications (optionnel, cron-able)
python manage.py send_reminders
```

| Compte de test | Rôle | Accès |
|---|---|---|
| `gerant@monexa.tg` | Gérant | Tout : anomalies, audit, sécurité, users |
| `comptable@monexa.tg` | Comptable | Validation, encaissements, exports |
| `caissier@monexa.tg` | Caissier | Saisie terrain (ses objets uniquement) |

Mot de passe : `Monexa2026!`

## 1. Tableau de bord (Gérant)
- KPIs temps réel : trésorerie par canal (T-Money / Moov / Flooz / Banque / Espèces), flux 7j/30j.
- Badge « Pipeline IA » visible sur **/securite/** : mode actif (LLM Vision / OCR local / démo).

## 2. Saisie terrain — réconciliation par IA
1. **Paiements** → « Analyser une photo de reçu » : pipeline IA (clé API si configurée, sinon OCR Tesseract local, sinon mock déterministe).
2. **Paiements** → « Coller un SMS » — exemples réels à coller :

```
Vous avez reçu 25 000 FCFA de KOSSI Mensah (90123456) le 24/09/2026 à 14:23. Ref: TMX260924.1432.A12345. Solde: 150 000 FCFA.
```
```
Transfert recu de AFI Adjovi (94123456). Montant: 10 000 FCFA. ID Transaction: MP260924.1430.B98765. Nouveau solde: 60 000 FCFA.
```
   → parsing **déterministe 100 % hors-ligne** (référence, montant, opérateur, payeur, date), puis matching automatique 4 niveaux.

## 3. Encaissement direct Mobile Money (Comptable+)
1. **Encaissements** → choisir une facture EN_ATTENTE + opérateur + téléphone du client.
2. En sandbox : bouton **« Simuler la validation client »** → la collection passe SUCCESS, un paiement `GW…` est créé et réconcilié automatiquement (audit immuable inclus).
3. En production : les clés API (`TMONEY_*`, `MOOV_*`, `FLOOZ_*`) activent le push réel ; l'opérateur notifie le webhook `POST /api/gateways/webhook/<operator>/` (signature HMAC requise).

## 4. Anti-fraude (Gérant)
- **Anomalies** : 4 règles métier (écart, sans facture, fenêtre temporelle, nocturne) + **scan anti-fraude SMS** (numéro usurpé vs préfixes opérateurs Togo, référence falsifiée, rafale du même émetteur, SMS d'hameçonnage) + Isolation Forest.
- Démonstration rapide : saisir un SMS avec un numéro Moov (94…) déclaré T-Money → « Numéro incompatible avec le canal ».

## 5. Sécurité — 2FA TOTP (Gérant)
1. **Sécurité** → « Activer la 2FA » → QR code → Google Authenticator → valider un code.
2. Se déconnecter / se reconnecter : étape 2 « code à 6 chiffres » exigée.
3. La 2FA est également togglable via l'API mobile (`PATCH /api/auth/me/2fa/`).

## 6. Prévisions & CFO
- Dashboard → prévision Holt-Winters J+7/J+30 avec intervalle 80 %.
- **Saisonnalité jours de marché** : `MARKET_DAYS=5` (samedi) booste les jours de grand marché, uplift calibré sur l'historique réel (ratio moyenne du jour / moyenne globale, borné [0.5, 2.0]).

## 7. Rapprochement bancaire multi-comptes (Comptable+)
1. **Banque** → importer le relevé CSV (ex. `docs/exemple_releve_bancaire.csv`).
2. MoneXa rapproche chaque virement automatiquement : référence facture dans le libellé → réconcilié ; montant+7j ou similarité → À VALIDER ; le reste → NON_RATTACHE. Idempotent (ré-importer ne crée aucun doublon).
3. CLI équivalente : `python manage.py import_bank_statement docs/exemple_releve_bancaire.csv`.

## 8. TresorIA & Exports
- **TresorIA** : questions en langage naturel sur les KPIs (jamais de SQL libre) — LLM réel si clé API, sinon moteur de règles hors-ligne.
- **TresorIA mobile** : nouvel écran Flutter (5e onglet) avec **saisie vocale** (micro) — FR / Ewé / Kabyé.
- **Exports** : CSV (Excel/SYSCOHADA) + **PDF présentables** : journal de caisse, bilan de trésorerie 30/90 jours, **facture client avec QR code**.

## 8-bis. Nouveautés V2.3 (WOW jury — 90 secondes)
1. **Facture PDF avec QR de paiement** → Factures → lien « PDF ↓ » sous la référence → le PDF s'ouvre : en-tête MoneXa, TOTAL À PAYER, QR code scannable (T-Money *880#, Moov *155#, Flooz *110#). Le jury scanne le QR avec son téléphone → il voit référence + montant. Factures échues marquées « EN RETARD » en rouge.
2. **Fiabilité clients** → Dashboard, dernière carte : score 0–100 par client (Fiable / Vigilance / Risque) calculé sur règlement, ponctualité, impayés et anomalies.
3. **Relances IA** → terminal : `python manage.py send_reminders --dry-run` → les messages de relance des factures > 7 j de retard, rédigés par l'IA (ou template hors-ligne). Sans `--dry-run` : notifications créées pour Gérant + Comptable (cloche en haut à droite).
4. **Rapport hebdo CFO** → terminal : `python manage.py generate_weekly_report` → bilan de la semaine chiffré + recommandation, livré en notification aux Gérants.

## 9. App mobile (Flutter)
- PWA installable (manifest MoneXa sur le web ET sur l'interface Django) + APK : `bash mobile_app/build_apk.sh`.
- **5 onglets** : Accueil, Reçu (IA), Paiements, TresorIA (vocal), Profil.
- **File de sync offline** : un reçu photographié sans réseau est stocké dans Hive et renvoyé automatiquement au démarrage/retour au premier plan — jamais de perte de preuve.
- Trilingue FR / Ewé / Kabyé.

## 10. Points techniques à citer au jury
- `DecimalField(14,2)` partout, `provider_ref` UNIQUE au niveau DB (anti-doublon natif).
- Audit immuable : hash-chain SHA-256, `save()`/`delete()` verrouillés, `verify_chain()` en direct sur la page Audit.
- RBAC 3 niveaux cohérent côté API (DRF permissions) et côté web (mixins).
- Tests : **99 tests pytest verts**, smoke tests web 23 + 14 vérifiés.
- PostgreSQL via `DATABASE_URL` (docker-compose fourni) ; SQLite fallback tests.
- TresorIA : LLM réel (GPT-4o-mini / Gemini) si clé API — KPIs pré-calculés injectés dans le prompt, **jamais de SQL, jamais d'accès DB** ; sinon moteur de règles déterministe 100 % hors-ligne (variable `TREASORIA_USE_LLM=0` pour forcer les règles).

## 11. Plan B — vidéo secours 60 s
- Script complet (storyboard seconde par seconde + voice-over + checklist de tournage) : **`docs/VIDEO_SECOURS.md`**.
- À tourner aujourd'hui, 2 copies physiques (clé USB + téléphone) + 1 lien cloud testé.
- À montrer UNIQUEMENT si la démo live est impossible (connexion, projector, Render down).
