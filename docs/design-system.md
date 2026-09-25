# Système de design MoneXa

## Palette de couleurs

Extraite du fichier `code couleur.jpeg` fourni avec le cahier des charges.

| Couleur | Hex | Usage |
|---|---|---|
| Bleu indigo profond | `#063082` | Primary — confiance fintech |
| Marine foncé | `#1A2539` | Texte, foreground — autorité |
| Crème chaud | `#FFFBF4` | Background — chaleur |
| Or | `#F59E0B` | Accent — CTA, Mobile Money |
| Vert émeraude | `#059669` | Success — validation, paiement OK |
| Rouge | `#DC2626` | Destructive — anomalies, erreur |
| Gris-bleu | `#9DA9C3` | Secondary — muted text |

## Couleurs par canal Mobile Money

| Canal | Couleur | Hex |
|---|---|---|
| T-Money | Indigo profond | `#063082` |
| Moov Money | Vert émeraude | `#059669` |
| Flooz | Or | `#F59E0B` |
| Banque | Gris-bleu | `#9DA9C3` |
| Espèces | Marine light | `#2C3E5A` |

## Typographie

- **Headings** : Plus Jakarta Sans (600/700)
- **Body** : Inter (400/500/600)
- **Mono** : JetBrains Mono (codes, références)

## Composants

### Cards
- Border radius : 16px
- Border : 1px solid `#CBD5E1`
- Padding : 16px (default), 24px (large)

### Boutons
- Primary : background `#F59E0B`, text `#1A2539`
- Elevated : padding `24px 14px`, radius `12px`

### KPI cards
- Icon en haut-gauche dans un carré arrondi avec background `color` alpha 0.1
- Valeur en grand (18px, bold)
- Label en dessous (12px, color muted)

### Audit log entries
- Hash SHA-256 tronqué à 16 caractères + `…`
- Couleur par statut d'action (vert = created, orange = warning, rouge = anomaly)

## Logo

```
+-----------------+
|     /\          |
|    /  \  MoneXa |
|   /----\        |
|  /      \       |
+-----------------+
```

Logo SVG dispo dans `mobile_app/lib/core/theme/app_colors.dart` (couleur) et repris sur le Django Admin.

## Iconographie

- **Lucide** (Flutter : Material Icons)
- Préférence pour les icônes outline, densité moyenne
- Tailles : 20 (inline), 24 (boutons), 44 (touch targets mobile)

## V2.4 — Images dynamiques & flux impeccable

Principes appliqués (inspirés taste-skill / impeccable.style / validation navigateur réel),
**progressive enhancement pur** : sans JS tout reste lisible ; aucune dépendance externe
(démo hors-ligne et Render-safe).

### Images dynamiques
- **Donut canaux** — SVG généré client-side depuis `data-donut` (JSON) : segments aux couleurs
  charte, balayage animé 0.85 s stagger 90 ms, total compact au centre (ex. « 44 M FCFA »).
- **Jauges radiales fiabilité** — `data-gauge` / `data-tone` : anneau 32 px, arc coloré
  (success/warning/danger), score au centre, `/100` en sous-texte.
- **Compteurs KPI** — `data-count` : count-up 700 ms ease-out cubic, `tabular-nums`
  (zéro décalage de layout), valeur finale = rendu serveur exact.
- **Aurore login** — 2 halos radiaux `blur(64px)` animés 22/28 s (GPU transform uniquement)
  + 3 pièces « M » dorées flottantes 9-11 s.
- **Empty states illustrés** — pseudo-élément CSS pur (tuile pointillée + motif), appliqué partout.

### Flux
- **View Transitions** (`@view-transition { navigation: auto }`) — fondu+glisse entre pages
  (Chrome/Edge 126+, fallback silencieux ailleurs).
- **Entrée orchestrée** — `.content > *` : `rise-in` 0.42 s, stagger 55 ms (cap 6 enfants).
- **Anti double-submit** — tout `form` : bouton `is-loading` (spinner) ou variante
  `data-loading-text` (« Analyse IA en cours… » sur l'upload preuve).
- **Flash messages** — auto-dismiss 6 s, sortie douce (opacity + translateY -8px),
  hit-area du bouton fermer étendue à 44 px.
- **TresorIA** — auto-scroll du fil + bulle « réfléchit » (3 dots animés) pendant le POST
  (couvre le timeout LLM jusqu'à 12 s).

### Règles de motion
- `prefers-reduced-motion: reduce` → toutes animations/transition/view-transitions neutralisées.
- Jamais `transition: all` ; GPU transform/opacity ; keyframes réservés aux séquences uniques.
- Feedback statique toujours présent (badge, couleur, libellé) — le mouvement ne porte jamais
  l'information seul.

### ⚠️ Localisation fr + attributs numériques (piège historique)
`LANGUAGE_CODE=fr` → Django rend les floats avec virgule (`45,3`). Conséquences :
- `style="--w: {{ x }}%"` = CSS invalide (bug latent V2, **corrigé** via `{{ x|unlocalize }}`).
- JSON inline dans `data-donut` : uniquement `|floatformat:0` (sûr) ou `|unlocalize` ;
  guillemets JSON = entités `&quot;` dans le template.
