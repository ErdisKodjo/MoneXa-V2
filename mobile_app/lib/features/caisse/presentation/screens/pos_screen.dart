import 'package:flutter/material.dart';

import '../../../../core/theme/app_colors.dart';
import '../../../../shared/utils/formatters.dart';
import '../../../../shared/widgets/status_badge.dart';
import '../../data/caisse_repository.dart';

/// Terminal de vente mobile (POS) — 3 onglets : Vendre / Ventes / Session.
/// Rejoue le même service que le terminal web (idempotence, multi-paiement,
/// stock, finance) — une seule source de vérité côté serveur.
class PosScreen extends StatefulWidget {
  const PosScreen({super.key, CaisseRepository? repository})
      : _injectedRepo = repository;

  /// Injection optionnelle (tests) — null = repository réseau réel.
  final CaisseRepository? _injectedRepo;

  @override
  State<PosScreen> createState() => _PosScreenState();
}

class _PosScreenState extends State<PosScreen> with SingleTickerProviderStateMixin {
  late final CaisseRepository _repo =
      widget._injectedRepo ?? CaisseRepository();

  late final TabController _tabController;

  // Catalogue
  List<CaisseProduit> _produits = [];
  String _recherche = '';
  String? _categorieFiltre;

  // Session + rapports
  CaisseSession? _session;
  RapportX? _rapport;

  // Ventes
  List<VentePos> _ventes = [];
  String _statutFiltre = 'TOUS';

  // Panier : produitId → quantité (+ snapshot produits pour affichage stable
  // même si la recherche serveur modifie la grille).
  final Map<int, double> _panier = {};
  final Map<int, CaisseProduit> _produitsConnus = {};

  bool _chargementProduits = true;
  bool _chargementSession = true;
  bool _chargementVentes = true;
  String? _erreurProduits;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 3, vsync: this);
    _tabController.addListener(() {
      if (_tabController.indexIsChanging && _tabController.index == 2) _chargerSession();
      if (_tabController.indexIsChanging && _tabController.index == 1) _chargerVentes();
    });
    _chargerProduits();
    _chargerSession();
    _chargerVentes();
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  Future<void> _chargerProduits({String? q}) async {
    setState(() {
      _chargementProduits = true;
      _erreurProduits = null;
    });
    try {
      final produits = await _repo.getProduits(q: q ?? _recherche);
      _produitsConnus.addAll({for (final p in produits) p.id: p});
      setState(() {
        _produits = produits;
        _chargementProduits = false;
      });
    } catch (_) {
      setState(() {
        _erreurProduits = 'Catalogue indisponible';
        _chargementProduits = false;
      });
    }
  }

  Future<void> _chargerSession() async {
    setState(() => _chargementSession = true);
    try {
      final (session, rapport) = await _repo.getSession();
      setState(() {
        _session = session;
        _rapport = rapport;
        _chargementSession = false;
      });
    } catch (_) {
      setState(() => _chargementSession = false);
    }
  }

  Future<void> _chargerVentes() async {
    setState(() => _chargementVentes = true);
    try {
      final ventes = await _repo.getVentes(statut: _statutFiltre);
      setState(() {
        _ventes = ventes;
        _chargementVentes = false;
      });
    } catch (_) {
      setState(() => _chargementVentes = false);
    }
  }

  // ── Panier ────────────────────────────────────────────────────────────

  double get _totalPanier {
    var total = 0.0;
    _panier.forEach((id, qte) {
      final prix = _produitsConnus[id]?.prixTtc ?? 0;
      total += prix * qte;
    });
    return total;
  }

  int get _nbArticles =>
      _panier.values.fold(0, (sum, q) => sum + q.round());

  void _ajouterAuPanier(CaisseProduit produit) {
    _produitsConnus[produit.id] = produit;
    setState(() => _panier[produit.id] = (_panier[produit.id] ?? 0) + 1);
  }

  Future<void> _apresVente() async {
    setState(_panier.clear);
    await Future.wait([_chargerProduits(), _chargerSession(), _chargerVentes()]);
  }

  void _ouvrirPanier() {
    if (_panier.isEmpty) return;
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (_) => _PanierSheet(
        panier: Map.of(_panier),
        produitsParId: {
          for (final id in _panier.keys)
            if (_produitsConnus[id] != null) id: _produitsConnus[id]!,
        },
        onEncaisser: _encaisser,
      ),
    );
  }

  /// Lance l'encaissement. En cas d'erreur métier (CaisseError serveur),
  /// relève l'exception : la feuille panier l'affiche elle-même (un SnackBar
  /// du parent passerait SOUS la feuille modale). En succès, ferme la feuille,
  /// rafraîchit (stock/session/ventes) et affiche le ticket.
  Future<void> _encaisser({
    required Map<int, double> panier,
    required String moyen,
    required double montant,
    required String reference,
    required String clientName,
    required String clientPhone,
  }) async {
    final lignes = panier.entries
        .map((e) => (produitId: e.key, quantite: e.value, remisePct: 0.0))
        .toList();
    final vente = await _repo.enregistrerVente(
      lignes: lignes,
      paiements: [(moyen: moyen, montant: montant, reference: reference)],
      clientName: clientName,
      clientPhone: clientPhone,
    );
    if (!mounted) return;
    Navigator.of(context).pop(); // ferme la feuille panier
    await _apresVente();
    _montrerTicket(vente);
  }

  void _montrerTicket(VentePos vente) {
    showDialog<void>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: Row(
          children: [
            const Icon(Icons.check_circle, color: AppColors.success),
            const SizedBox(width: 8),
            Expanded(child: Text('Vente ${vente.reference}', style: const TextStyle(fontSize: 18))),
          ],
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(Formatters.formatFcfa(vente.totalTtc),
                style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w800, color: AppColors.primary),),
            if (vente.rendu > 0)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text('Monnaie rendue : ${Formatters.formatFcfa(vente.rendu)}',
                    style: const TextStyle(color: AppColors.muted),),
              ),
            const SizedBox(height: 8),
            ...vente.paiements.map(
              (p) => Text('${p.moyenDisplay} : ${Formatters.formatFcfa(p.montant)}'),
            ),
          ],
        ),
        actions: [
          FilledButton(
            onPressed: () => Navigator.of(dialogContext).pop(),
            child: const Text('Nouvelle vente'),
          ),
        ],
      ),
    );
  }

  // ── Build ─────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Caisse POS'),
        bottom: TabBar(
          controller: _tabController,
          labelColor: AppColors.primary,
          unselectedLabelColor: AppColors.muted,
          indicatorColor: AppColors.gold,
          tabs: const [
            Tab(text: 'Vendre', icon: Icon(Icons.point_of_sale)),
            Tab(text: 'Ventes', icon: Icon(Icons.receipt_long)),
            Tab(text: 'Session', icon: Icon(Icons.savings)),
          ],
        ),
      ),
      body: TabBarView(
        controller: _tabController,
        children: [
          _ongletVendre(),
          _ongletVentes(),
          _ongletSession(),
        ],
      ),
    );
  }

  // ── Onglet 1 : Vendre ─────────────────────────────────────────────────

  Widget _ongletVendre() {
    final categories = _produits
        .map((p) => p.categorieNom)
        .where((c) => c.isNotEmpty)
        .toSet()
        .toList();
    return Column(
      children: [
        if (_session == null && !_chargementSession)
          _BandeauPasDeSession(onOuvrir: _dialogueOuvertureSession),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
          child: TextField(
            decoration: InputDecoration(
              hintText: 'Rechercher (nom, référence, EAN)…',
              prefixIcon: const Icon(Icons.search),
              suffixIcon: _recherche.isEmpty
                  ? const Icon(Icons.qr_code_scanner, color: AppColors.muted)
                  : IconButton(
                      icon: const Icon(Icons.clear),
                      onPressed: () {
                        setState(() => _recherche = '');
                        _chargerProduits(q: '');
                      },
                    ),
            ),
            onChanged: (value) {
              _recherche = value;
              _chargerProduits(q: value);
            },
          ),
        ),
        if (categories.isNotEmpty)
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            child: Row(
              children: [
                _chipCategorie(null),
                ...categories.map(_chipCategorie),
              ],
            ),
          ),
        Expanded(child: _grilleProduits()),
        _barrePanier(),
      ],
    );
  }

  Widget _chipCategorie(String? nom) {
    final selectionnee = _categorieFiltre == nom;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 4),
      child: FilterChip(
        label: Text(nom ?? 'Tout'),
        selected: selectionnee,
        onSelected: (_) => setState(() => _categorieFiltre = selectionnee ? null : nom),
        selectedColor: AppColors.primary,
        labelStyle: TextStyle(color: selectionnee ? Colors.white : AppColors.navy),
        checkmarkColor: Colors.white,
      ),
    );
  }

  List<CaisseProduit> get _produitsFiltres {
    if (_categorieFiltre == null) return _produits;
    return _produits.where((p) => p.categorieNom == _categorieFiltre).toList();
  }

  Widget _grilleProduits() {
    if (_chargementProduits) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_erreurProduits != null) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.cloud_off, size: 48, color: AppColors.muted),
            const SizedBox(height: 12),
            Text(_erreurProduits!),
            TextButton(onPressed: _chargerProduits, child: const Text('Réessayer')),
          ],
        ),
      );
    }
    final produits = _produitsFiltres;
    if (produits.isEmpty) {
      return const Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.inventory_2_outlined, size: 48, color: AppColors.muted),
            SizedBox(height: 12),
            Text('Aucun produit', style: TextStyle(color: AppColors.muted)),
          ],
        ),
      );
    }
    return RefreshIndicator(
      onRefresh: () => _chargerProduits(),
      child: GridView.builder(
        padding: const EdgeInsets.all(16),
        gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
          crossAxisCount: 2,
          mainAxisSpacing: 12,
          crossAxisSpacing: 12,
          childAspectRatio: 1.40,
        ),
        itemCount: produits.length,
        itemBuilder: (context, index) => _carteProduit(produits[index]),
      ),
    );
  }

  Widget _carteProduit(CaisseProduit produit) {
    final couleur = produit.categorieCouleur.startsWith('#')
        ? Color(int.parse('FF${produit.categorieCouleur.substring(1)}', radix: 16))
        : AppColors.primary;
    final dansPanier = _panier[produit.id] ?? 0;
    return Material(
      color: AppColors.surface,
      borderRadius: BorderRadius.circular(16),
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: () => _ajouterAuPanier(produit),
        child: Container(
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(16),
            border: Border.all(
              color: dansPanier > 0 ? AppColors.gold : AppColors.border,
              width: dansPanier > 0 ? 1.5 : 1,
            ),
          ),
          padding: const EdgeInsets.all(12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  if (produit.categorieNom.isNotEmpty)
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                      decoration: BoxDecoration(
                        color: couleur.withValues(alpha: 0.15),
                        borderRadius: BorderRadius.circular(999),
                      ),
                      child: Text(
                        produit.categorieNom,
                        style: TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: couleur),
                      ),
                    ),
                  const Spacer(),
                  if (produit.stockBas)
                    const Icon(Icons.warning_amber_rounded, size: 16, color: AppColors.danger),
                ],
              ),
              const Spacer(),
              Text(
                produit.designation,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13),
              ),
              const SizedBox(height: 4),
              Row(
                children: [
                  Expanded(
                    child: Text(
                      Formatters.formatFcfa(produit.prixTtc),
                      style: const TextStyle(
                        fontWeight: FontWeight.w800,
                        fontSize: 14,
                        color: AppColors.primary,
                      ),
                    ),
                  ),
                  if (dansPanier > 0)
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                      decoration: BoxDecoration(
                        color: AppColors.gold,
                        borderRadius: BorderRadius.circular(999),
                      ),
                      child: Text(
                        '×${dansPanier.round()}',
                        style: const TextStyle(
                          fontWeight: FontWeight.w800,
                          fontSize: 12,
                          color: AppColors.navy,
                        ),
                      ),
                    ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _barrePanier() {
    final vide = _panier.isEmpty;
    return SafeArea(
      top: false,
      child: Container(
        margin: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: vide ? AppColors.surface : AppColors.primary,
          borderRadius: BorderRadius.circular(16),
          border: vide ? const Border.fromBorderSide(BorderSide(color: AppColors.border)) : null,
          boxShadow: vide
              ? null
              : [BoxShadow(color: AppColors.primary.withValues(alpha: 0.3), blurRadius: 12, offset: const Offset(0, 4))],
        ),
        child: Material(
          color: Colors.transparent,
          child: InkWell(
            borderRadius: BorderRadius.circular(16),
            onTap: vide ? null : _ouvrirPanier,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
              child: Row(
                children: [
                  Icon(Icons.shopping_cart, color: vide ? AppColors.muted : Colors.white),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Text(
                      vide ? 'Panier vide — touchez un produit' : '$_nbArticles article(s)',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        fontWeight: FontWeight.w700,
                        color: vide ? AppColors.muted : Colors.white,
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Text(
                    Formatters.formatFcfa(_totalPanier),
                    style: TextStyle(
                      fontWeight: FontWeight.w800,
                      fontSize: 16,
                      color: vide ? AppColors.muted : AppColors.gold,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  // ── Onglet 2 : Ventes ─────────────────────────────────────────────────

  Widget _ongletVentes() {
    return Column(
      children: [
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          child: Row(
            children: [
              _chipStatut('TOUS', 'Toutes'),
              _chipStatut('VALIDEE', 'Validées'),
              _chipStatut('ANNULEE', 'Annulées'),
            ],
          ),
        ),
        Expanded(child: _listeVentes()),
      ],
    );
  }

  Widget _chipStatut(String valeur, String label) {
    final selectionne = _statutFiltre == valeur;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 4),
      child: FilterChip(
        label: Text(label),
        selected: selectionne,
        onSelected: (_) {
          setState(() => _statutFiltre = valeur);
          _chargerVentes();
        },
        selectedColor: AppColors.primary,
        labelStyle: TextStyle(color: selectionne ? Colors.white : AppColors.navy),
        checkmarkColor: Colors.white,
      ),
    );
  }

  Widget _listeVentes() {
    if (_chargementVentes) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_ventes.isEmpty) {
      return const Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.receipt_long, size: 48, color: AppColors.muted),
            SizedBox(height: 12),
            Text('Aucune vente', style: TextStyle(color: AppColors.muted)),
          ],
        ),
      );
    }
    return RefreshIndicator(
      onRefresh: _chargerVentes,
      child: ListView.separated(
        padding: const EdgeInsets.all(16),
        itemCount: _ventes.length,
        separatorBuilder: (_, __) => const SizedBox(height: 10),
        itemBuilder: (context, index) {
          final vente = _ventes[index];
          return Container(
            decoration: BoxDecoration(
              color: AppColors.surface,
              borderRadius: BorderRadius.circular(16),
              border: Border.all(color: AppColors.border),
            ),
            child: ListTile(
              contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
              onTap: () => _montrerDetailVente(vente),
              title: Text(
                vente.reference,
                style: const TextStyle(fontWeight: FontWeight.w800),
              ),
              subtitle: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(vente.clientName.isEmpty
                      ? 'Client anonyme'
                      : vente.clientName,),
                  Text(
                    '${vente.lignes.length} ligne(s) · ${Formatters.formatShortDate(vente.createdAt)}',
                    style: const TextStyle(fontSize: 12, color: AppColors.muted),
                  ),
                ],
              ),
              trailing: Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Text(
                    Formatters.formatFcfa(vente.totalTtc),
                    style: const TextStyle(fontWeight: FontWeight.w800, color: AppColors.primary),
                  ),
                  const SizedBox(height: 4),
                  StatusBadge(status: vente.statut),
                ],
              ),
            ),
          );
        },
      ),
    );
  }

  void _montrerDetailVente(VentePos vente) {
    showDialog<void>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: Text('Vente ${vente.reference}'),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              ...vente.lignes.map(
                (l) => Padding(
                  padding: const EdgeInsets.symmetric(vertical: 2),
                  child: Row(
                    children: [
                      Expanded(child: Text('${l.designation} ×${l.quantite.round()}')),
                      Text(Formatters.formatFcfa(l.totalTtc),
                          style: const TextStyle(fontWeight: FontWeight.w700),),
                    ],
                  ),
                ),
              ),
              const Divider(height: 16),
              ...vente.paiements.map(
                (p) => Padding(
                  padding: const EdgeInsets.symmetric(vertical: 2),
                  child: Row(
                    children: [
                      Expanded(child: Text(p.moyenDisplay)),
                      Text(Formatters.formatFcfa(p.montant)),
                    ],
                  ),
                ),
              ),
              if (vente.rendu > 0)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 2),
                  child: Row(
                    children: [
                      const Expanded(child: Text('Rendu')),
                      Text('-${Formatters.formatFcfa(vente.rendu)}'),
                    ],
                  ),
                ),
              const Divider(height: 16),
              Row(
                children: [
                  const Expanded(child: Text('TOTAL', style: TextStyle(fontWeight: FontWeight.w800))),
                  Text(Formatters.formatFcfa(vente.totalTtc),
                      style: const TextStyle(fontWeight: FontWeight.w800, color: AppColors.primary),),
                ],
              ),
              const SizedBox(height: 8),
              StatusBadge(status: vente.statut),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(),
            child: const Text('Fermer'),
          ),
        ],
      ),
    );
  }

  // ── Onglet 3 : Session ────────────────────────────────────────────────

  Widget _ongletSession() {
    if (_chargementSession) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_session == null) {
      return _SessionFermee(onOuvrir: _dialogueOuvertureSession);
    }
    return RefreshIndicator(
      onRefresh: _chargerSession,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _carteSession(),
          const SizedBox(height: 16),
          if (_rapport != null) _carteRapportX(),
          const SizedBox(height: 16),
          FilledButton.icon(
            onPressed: _dialogueClotureSession,
            style: FilledButton.styleFrom(backgroundColor: AppColors.danger),
            icon: const Icon(Icons.lock_outline),
            label: const Text('Clôturer la session (Z)'),
          ),
        ],
      ),
    );
  }

  Widget _carteSession() {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.success.withValues(alpha: 0.5)),
      ),
      child: Row(
        children: [
          CircleAvatar(
            backgroundColor: AppColors.success.withValues(alpha: 0.15),
            child: const Icon(Icons.storefront, color: AppColors.success),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Session ouverte — ${_session!.vendeurNom}',
                    style: const TextStyle(fontWeight: FontWeight.w800),),
                const SizedBox(height: 2),
                Text(
                  'Fond de caisse : ${Formatters.formatFcfa(_session!.fondCaisse)}'
                  ' · ouverte ${Formatters.formatShortDate(_session!.ouverteAt)}',
                  style: const TextStyle(color: AppColors.muted, fontSize: 12),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _carteRapportX() {
    final rapport = _rapport!;
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('Rapport X (à chaud)',
              style: TextStyle(fontWeight: FontWeight.w800, fontSize: 15),),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: _rapportKpi('Total TTC', Formatters.formatFcfa(rapport.totalTtc), AppColors.primary),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: _rapportKpi('Tickets', '${rapport.nbTickets}', AppColors.gold),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: _rapportKpi('Panier moyen', Formatters.formatFcfa(rapport.panierMoyen), AppColors.success),
              ),
            ],
          ),
          const SizedBox(height: 12),
          if (rapport.parMoyen.isEmpty)
            const Text('Aucune vente dans cette session.',
                style: TextStyle(color: AppColors.muted),)
          else
            ...rapport.parMoyen.map(
              (m) => ListTile(
                contentPadding: EdgeInsets.zero,
                dense: true,
                leading: CircleAvatar(
                  backgroundColor: AppColors.channelColor(m.moyen).withValues(alpha: 0.15),
                  child: Icon(Icons.payments, size: 18, color: AppColors.channelColor(m.moyen)),
                ),
                title: Text(m.label),
                trailing: Text(
                  '${Formatters.formatFcfa(m.montant)}  (${m.nb})',
                  style: const TextStyle(fontWeight: FontWeight.w700),
                ),
              ),
            ),
          const Divider(),
          Row(
            children: [
              const Expanded(child: Text('Espèces théoriques en caisse')),
              Text(
                Formatters.formatFcfa(rapport.especesTheorique),
                style: const TextStyle(fontWeight: FontWeight.w800),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _rapportKpi(String label, String valeur, Color couleur) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: couleur.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: const TextStyle(fontSize: 11, color: AppColors.muted)),
          const SizedBox(height: 4),
          Text(valeur,
              style: TextStyle(fontWeight: FontWeight.w800, fontSize: 13, color: couleur),),
        ],
      ),
    );
  }

  // ── Dialogues session ─────────────────────────────────────────────────

  Future<void> _dialogueOuvertureSession() async {
    final fondController = TextEditingController(text: '0');
    final confirme = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: const Text('Ouvrir la caisse'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text('Déclarez le fond de caisse initial (espèces).'),
            const SizedBox(height: 12),
            TextField(
              controller: fondController,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              decoration: const InputDecoration(labelText: 'Fond de caisse (FCFA)'),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text('Annuler'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: const Text('Ouvrir'),
          ),
        ],
      ),
    );
    if (confirme != true || !mounted) return;
    final fond = double.tryParse(fondController.text.replaceAll(',', '.')) ?? 0;
    try {
      await _repo.ouvrirSession(fond);
      await _chargerSession();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Caisse ouverte — bonne vente !'), backgroundColor: AppColors.success),
      );
    } on CaisseException catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
        ..hideCurrentSnackBar()
        ..showSnackBar(SnackBar(content: Text(e.message), backgroundColor: AppColors.danger));
    }
  }

  Future<void> _dialogueClotureSession() async {
    final comptageController = TextEditingController();
    final noteController = TextEditingController();
    final confirme = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: const Text('Clôturer la session'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              'Espèces théoriques attendues : ${Formatters.formatFcfa(_rapport?.especesTheorique ?? 0)}',
              style: const TextStyle(fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: comptageController,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              decoration: const InputDecoration(labelText: 'Comptage physique (FCFA)'),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: noteController,
              decoration: const InputDecoration(labelText: 'Note (facultatif)'),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text('Annuler'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: AppColors.danger),
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: const Text('Clôturer'),
          ),
        ],
      ),
    );
    if (confirme != true || !mounted) return;
    final comptage = double.tryParse(comptageController.text.replaceAll(',', '.')) ?? 0;
    try {
      final fermee = await _repo.cloturerSession(comptage, note: noteController.text);
      await _chargerSession();
      if (!mounted) return;
      final ecart = fermee.ecart ?? 0;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            ecart == 0
                ? 'Session clôturée — caisse exacte.'
                : 'Session clôturée — écart de ${Formatters.formatFcfa(ecart.abs())} '
                    '${ecart < 0 ? '(manquant)' : '(excédent)'} signalé au gérant.',
          ),
          backgroundColor: ecart == 0 ? AppColors.success : AppColors.gold,
        ),
      );
    } on CaisseException catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
        ..hideCurrentSnackBar()
        ..showSnackBar(SnackBar(content: Text(e.message), backgroundColor: AppColors.danger));
    }
  }
}

// ─────────────────────────────────────────────────────────────────────────
// Widgets internes
// ─────────────────────────────────────────────────────────────────────────

class _BandeauPasDeSession extends StatelessWidget {
  const _BandeauPasDeSession({required this.onOuvrir});

  final VoidCallback onOuvrir;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.fromLTRB(16, 12, 16, 0),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.gold.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.gold.withValues(alpha: 0.5)),
      ),
      child: Row(
        children: [
          const Icon(Icons.lock_clock, color: AppColors.gold),
          const SizedBox(width: 12),
          const Expanded(child: Text('Aucune session de caisse ouverte.')),
          TextButton(onPressed: onOuvrir, child: const Text('Ouvrir')),
        ],
      ),
    );
  }
}

class _SessionFermee extends StatelessWidget {
  const _SessionFermee({required this.onOuvrir});

  final VoidCallback onOuvrir;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.savings_outlined, size: 64, color: AppColors.muted),
          const SizedBox(height: 16),
          const Text('Caisse fermée', style: TextStyle(fontWeight: FontWeight.w800, fontSize: 18)),
          const SizedBox(height: 4),
          const Text('Ouvrez une session pour commencer à vendre.',
              style: TextStyle(color: AppColors.muted),),
          const SizedBox(height: 20),
          FilledButton.icon(
            onPressed: onOuvrir,
            icon: const Icon(Icons.lock_open),
            label: const Text('Ouvrir la caisse'),
          ),
        ],
      ),
    );
  }
}

/// Feuille panier : quantités, paiement unique, encaissement.
class _PanierSheet extends StatefulWidget {
  const _PanierSheet({
    required this.panier,
    required this.produitsParId,
    required this.onEncaisser,
  });

  final Map<int, double> panier;
  final Map<int, CaisseProduit> produitsParId;
  final Future<void> Function({
    required Map<int, double> panier,
    required String moyen,
    required double montant,
    required String reference,
    required String clientName,
    required String clientPhone,
  }) onEncaisser;

  @override
  State<_PanierSheet> createState() => _PanierSheetState();
}

class _PanierSheetState extends State<_PanierSheet> {
  late Map<int, double> _panier;
  String _moyen = 'ESPECES';
  final _montantController = TextEditingController();
  final _referenceController = TextEditingController();
  final _clientController = TextEditingController();
  final _phoneController = TextEditingController();
  bool _encours = false;
  String? _erreur;

  static const Map<String, String> _moyensLabels = {
    'ESPECES': 'Espèces',
    'TMONEY': 'T-Money',
    'MOOV': 'Moov Money',
    'FLOOZ': 'Flooz',
    'CARTE': 'Carte',
  };

  @override
  void initState() {
    super.initState();
    _panier = Map.of(widget.panier);
    _majMontantSuggere();
  }

  @override
  void dispose() {
    _montantController.dispose();
    _referenceController.dispose();
    _clientController.dispose();
    _phoneController.dispose();
    super.dispose();
  }

  double get _total {
    var total = 0.0;
    _panier.forEach((id, qte) {
      total += (widget.produitsParId[id]?.prixTtc ?? 0) * qte;
    });
    return total;
  }

  void _majMontantSuggere() {
    final total = _total;
    if (_moyen == 'ESPECES') {
      // Suggère l'arrondi supérieur en billets de 500 (contexte FCFA).
      final billets = (total / 500).ceil() * 500;
      _montantController.text = billets.toStringAsFixed(0);
    } else {
      _montantController.text = total.toStringAsFixed(0);
    }
  }

  Future<void> _encaisser() async {
    final montant =
        double.tryParse(_montantController.text.replaceAll(' ', '').replaceAll(',', '.')) ?? 0;
    if (_panier.isEmpty) {
      setState(() => _erreur = 'Le panier est vide.');
      return;
    }
    if (montant <= 0) {
      setState(() => _erreur = 'Saisissez le montant encaissé.');
      return;
    }
    setState(() {
      _encours = true;
      _erreur = null;
    });
    try {
      await widget.onEncaisser(
        panier: _panier,
        moyen: _moyen,
        montant: montant,
        reference: _referenceController.text.trim(),
        clientName: _clientController.text.trim(),
        clientPhone: _phoneController.text.trim(),
      );
    } on CaisseException catch (e) {
      if (mounted) {
        setState(() {
        _encours = false;
        _erreur = e.message;
      });
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          _encours = false;
          _erreur = 'Encaissement impossible — vérifiez la connexion.';
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final rendu = _moyen == 'ESPECES'
        ? ((double.tryParse(_montantController.text.replaceAll(' ', '').replaceAll(',', '.')) ?? 0) - _total)
        : 0.0;
    return SafeArea(
      child: Padding(
        padding: EdgeInsets.only(
          left: 20,
          right: 20,
          top: 16,
          bottom: MediaQuery.of(context).viewInsets.bottom + 16,
        ),
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Text('Panier', style: TextStyle(fontWeight: FontWeight.w800, fontSize: 18)),
                  const Spacer(),
                  Text(Formatters.formatFcfa(_total),
                      style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 18, color: AppColors.primary),),
                ],
              ),
              const SizedBox(height: 8),
              ..._panier.entries.map((entry) {
                final produit = widget.produitsParId[entry.key];
                if (produit == null) return const SizedBox.shrink();
                return ListTile(
                  contentPadding: EdgeInsets.zero,
                  dense: true,
                  title: Text(produit.designation, maxLines: 1, overflow: TextOverflow.ellipsis),
                  subtitle: Text(Formatters.formatFcfa(produit.prixTtc)),
                  trailing: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      IconButton(
                        icon: const Icon(Icons.remove_circle_outline),
                        onPressed: () {
                          setState(() {
                            final q = (_panier[produit.id] ?? 0) - 1;
                            if (q <= 0) {
                              _panier.remove(produit.id);
                            } else {
                              _panier[produit.id] = q;
                            }
                          });
                        },
                      ),
                      Text('${entry.value.round()}',
                          style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 15),),
                      IconButton(
                        icon: const Icon(Icons.add_circle_outline, color: AppColors.primary),
                        onPressed: () {
                          setState(() => _panier[produit.id] = (_panier[produit.id] ?? 0) + 1);
                        },
                      ),
                      const SizedBox(width: 8),
                      SizedBox(
                        width: 92,
                        child: Text(
                          Formatters.formatFcfa(produit.prixTtc * entry.value),
                          textAlign: TextAlign.end,
                          style: const TextStyle(fontWeight: FontWeight.w700),
                        ),
                      ),
                    ],
                  ),
                );
              }),
              if (_panier.isEmpty)
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 24),
                  child: Center(child: Text('Panier vide', style: TextStyle(color: AppColors.muted))),
                ),
              const Divider(),
              const Text('Moyen de paiement', style: TextStyle(fontWeight: FontWeight.w700)),
              const SizedBox(height: 8),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: _moyensLabels.entries.map((entry) {
                  final selectionne = _moyen == entry.key;
                  return ChoiceChip(
                    label: Text(entry.value),
                    selected: selectionne,
                    onSelected: (_) {
                      setState(() {
                        _moyen = entry.key;
                        _majMontantSuggere();
                      });
                    },
                    selectedColor: AppColors.channelColor(entry.key),
                    labelStyle: TextStyle(color: selectionne ? Colors.white : AppColors.navy),
                    checkmarkColor: Colors.white,
                  );
                }).toList(),
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _montantController,
                      keyboardType: const TextInputType.numberWithOptions(decimal: true),
                      decoration: InputDecoration(
                        labelText: _moyen == 'ESPECES' ? 'Montant reçu (FCFA)' : 'Montant encaissé (FCFA)',
                      ),
                      onChanged: (_) => setState(() {}),
                    ),
                  ),
                  if (_moyen != 'ESPECES') ...[
                    const SizedBox(width: 12),
                    Expanded(
                      child: TextField(
                        controller: _referenceController,
                        decoration: const InputDecoration(labelText: 'N° transaction'),
                      ),
                    ),
                  ],
                ],
              ),
              if (_moyen == 'ESPECES') ...[
                const SizedBox(height: 6),
                Text(
                  rendu >= 0
                      ? 'À rendre : ${Formatters.formatFcfa(rendu)}'
                      : 'Il manque ${Formatters.formatFcfa(-rendu)} !',
                  style: TextStyle(
                    fontWeight: FontWeight.w800,
                    color: rendu >= 0 ? AppColors.success : AppColors.danger,
                  ),
                ),
              ],
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _clientController,
                      decoration: const InputDecoration(labelText: 'Client (facultatif)'),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: TextField(
                      controller: _phoneController,
                      keyboardType: TextInputType.phone,
                      decoration: const InputDecoration(labelText: 'Téléphone'),
                    ),
                  ),
                ],
              ),
              if (_erreur != null)
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Text(_erreur!, style: const TextStyle(color: AppColors.danger)),
                ),
              const SizedBox(height: 16),
              SizedBox(
                width: double.infinity,
                child: FilledButton.icon(
                  onPressed: (_encours || _panier.isEmpty) ? null : _encaisser,
                  icon: _encours
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2, color: AppColors.navy),
                        )
                      : const Icon(Icons.check_circle),
                  label: Text(_encours ? 'Encaissement…' : 'Encaisser ${Formatters.formatFcfa(_total)}'),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
