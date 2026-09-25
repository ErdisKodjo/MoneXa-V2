# 🎥 MoneXa — Vidéo secours 60 secondes (backup démo live)

> **Rôle de cette vidéo** : plan B si la connexion / le projector / Render lâche
> pendant la démo live de dimanche. Elle est tournée UNE FOIS, stockée en local
> (téléphone + clé USB + drive), et N'EST montrée QUE si besoin.
> Alignée sur les 2 WOW du pitch : réconciliation IA + audit immuable.

## 1. Specs de rendu

| Paramètre | Valeur |
|---|---|
| Durée | 60 s max (chrono) |
| Résolution | 1920×1080, 30 fps |
| Format | MP4 (H.264 + AAC) |
| Voix | Voice-over FR enregistré au casque (ou voix off lue en direct) |
| Outil | OBS Studio (gratuit) — enregistrement écran + micro |
| Nom de fichier | `MoneXa_secours_60s.mp4` |

## 2. Préparation du tournage (10 minutes, à faire AVANT)

```bash
# Terminal 1 — backend avec données de démo fraîches
cd backend && source .venv/bin/activate
python manage.py migrate && python manage.py seed_demo --reset
python manage.py runserver
```

- [ ] Onglet 1 : `http://localhost:8000/` → dashboard Gérant (`gerant@monexa.tg` / `Monexa2026!`)
- [ ] Onglet 2 : page **Paiements** → formulaire « Coller un SMS » PRÊT
- [ ] Presse-papiers : le SMS T-Money ci-dessous COPIÉ (Ctrl+V instantané)
- [ ] Onglet 3 : page **Audit** (pour la vérification de chaîne en 1 clic)
- [ ] OBS : scène plein écran capturant le navigateur, micro testé (niveau -6 dB)
- [ ] Fermer les notifications (mode ne pas déranger), zoom navigateur 100 %

**SMS à copier dans le presse-papiers :**
```
Vous avez reçu 25 000 FCFA de KOSSI Mensah (90123456) le 24/09/2026 à 14:23. Ref: TMX260924.1432.A12345. Solde: 150 000 FCFA.
```

**SMS anti-fraude (plan B tourné en second, montage facultatif) :**
```
Vous avez reçu 75 000 FCFA de Inconnu (94123456) le 26/09/2026 à 02:45. Ref: TMXFAKE999. Solde: 90 000 FCFA.
```

## 3. Storyboard seconde par seconde

| ⏱ Timecode | 🎬 À l'écran | 🎙 Voice-over |
|---|---|---|
| 0:00–0:07 | Logo MoneXa plein écran (MONEXA_LOGO.png), sous-titre « CFO virtuel des PME ouest-africaines » | « Et si chaque paiement Mobile Money de votre PME était comptabilisé, réconcilié et audité — automatiquement ? Voici MoneXa. » |
| 0:07–0:20 | Onglet Paiements → Ctrl+V du SMS T-Money → clic Analyser → résultat extraction (montant, réf, payeur, confiance IA) | « On colle un vrai SMS T-Money. L'IA extrait le montant, la référence, le payeur — en une seconde, sans ressaisie. » |
| 0:20–0:32 | Le paiement apparaît RÉCONCILIÉ → clic sur la facture liée → statut passe à payé | « Le moteur de réconciliation le rattache automatiquement à la bonne facture : par référence, par montant, ou par similarité. Fini les paiements perdus. » |
| 0:32–0:44 | Onglet Audit → clic « Vérifier la chaîne » → badge ✅ chaîne intègre ; bref passage page Anomalies | « Chaque opération est scellée dans un audit immuable à chaînage de hachages SHA-256. Toute fraude — doublon, numéro usurpé, rafale — est signalée. » |
| 0:44–0:53 | Page TresorIA → taper « Quelle est ma trésorerie à 30 jours ? » → réponse avec chiffres | « TresorIA, le CFO virtuel, répond en langage naturel : trésorerie, prévisions, impayés — sans jamais toucher directement à la base. » |
| 0:53–1:00 | Capture app Flutter (téléphone ou émulateur) : dashboard KPIs → écran upload → logo final + « MoneXa — Défi 2, D3BUG 0R DI3 » | « Et tout est accessible hors-ligne depuis le mobile, en français, en éwé ou en kabyé. MoneXa — la finance, simplifiée. » |

> **Total voice-over : ~155 mots** — débit calme ≈ 2,6 mots/seconde. Répéter 2 fois avant d'enregistrer.

## 4. Checklist pendant l'enregistrement

- [ ] Cursor au ralenti et précis (le jury suit la souris, pas le code)
- [ ] Aucune hesitation « euh » → si erreur, reprendre LE PLAN concerné, pas toute la vidéo
- [ ] Clic sur « Analyser » : laisser le loader IA apparaître 1 s max (montage : couper l'attente si > 2 s)
- [ ] Vérifier que les montants affichés correspondent au voice-over
- [ ] Limite stricte : si ça dépasse 60 s → couper le plan 0:44–0:53 (TresorIA est aussi démo live)

## 5. Diffusion & secours du secours

1. **Local** : clé USB + stockage téléphone (2 copies physiques)
2. **Cloud** : lien de partage direct (Drive), testé depuis un autre appareil
3. **Sans écran** : la voix-over seule + les captures PNG des 5 écrans permettent un pitch audio de secours
4. Après tournage : regarder la vidéo ENTIÈRE une fois sur le projecteur réel si possible (test de lisibilité des petites polices)
