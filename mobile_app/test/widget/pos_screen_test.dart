import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:monexa/features/caisse/data/caisse_repository.dart';
import 'package:monexa/features/caisse/presentation/screens/pos_screen.dart';

/// Faux repository — données immédiates, zéro réseau (pas de timers pendants).
class _FakeCaisseRepo implements CaisseRepository {
  _FakeCaisseRepo({this.produits = const [], this.session, this.rapport});

  final List<CaisseProduit> produits;
  final CaisseSession? session;
  final RapportX? rapport;
  final List<VentePos> ventes = const [];

  @override
  Future<List<CaisseProduit>> getProduits({String? q}) async => produits;

  @override
  Future<(CaisseSession?, RapportX?)> getSession() async => (session, rapport);

  @override
  Future<CaisseSession> ouvrirSession(double fondCaisse) async =>
      session ?? _sessionOuverte;

  @override
  Future<CaisseSession> cloturerSession(double comptagePhysique, {String note = ''}) async =>
      session ?? _sessionOuverte;

  @override
  Future<List<VentePos>> getVentes({String? statut, String? q}) async => ventes;

  @override
  Future<VentePos> enregistrerVente({
    required List<({int produitId, double quantite, double remisePct})> lignes,
    required List<({String moyen, double montant, String reference})> paiements,
    double remisePanierPct = 0,
    String clientName = '',
    String clientPhone = '',
    String? idempotenceKey,
  }) async =>
      ventes.first;

  // Les membres concrets du repository réel ne sont pas utilisés par l'écran.
  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

final _sessionOuverte = CaisseSession(
  id: 1,
  statut: 'OUVERTE',
  vendeurNom: 'Kodjo Caissier',
  fondCaisse: 5000,
  ouverteAt: null,
);

/// Surface portrait type téléphone — la surface par défaut des tests
/// (800×600 paysage) coupe la grille produits sous le fold et fausse les
/// taps (widgets présents dans l'arbre mais clippés hors viewport).
Future<void> _pumpPos(WidgetTester tester, CaisseRepository repo) async {
  tester.view.physicalSize = const Size(412, 915);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(MaterialApp(home: PosScreen(repository: repo)));
}

CaisseProduit _riz() => CaisseProduit(
      id: 1,
      reference: 'ART-RIZ01',
      ean: '',
      designation: 'Sac de riz 50kg',
      categorieNom: 'Alimentation',
      categorieCouleur: '#063082',
      unite: 'pièce',
      prixTtc: 25000,
      stock: 20,
      stockBas: false,
    );

void main() {
  testWidgets('PosScreen sans session : bandeau ouverture + catalogue rendu',
      (tester) async {
    await _pumpPos(tester, _FakeCaisseRepo(produits: [_riz()]));
    await tester.pumpAndSettle();

    // Bandeau d'alerte session + onglet Vendre actif
    expect(find.text('Aucune session de caisse ouverte.'), findsOneWidget);
    // Grille produits : la carte affiche désignation + prix
    expect(find.text('Sac de riz 50kg'), findsOneWidget);
    expect(find.text('25 000 FCFA'), findsOneWidget);
  });

  testWidgets('PosScreen : toucher un produit remplit le panier (total juste)',
      (tester) async {
    await _pumpPos(tester, _FakeCaisseRepo(produits: [_riz()]));
    await tester.pumpAndSettle();

    await tester.tap(find.text('Sac de riz 50kg'));
    await tester.pumpAndSettle();

    // Barre panier : 1 article, total = prix produit
    expect(find.text('1 article(s)'), findsOneWidget);
    expect(find.text('25 000 FCFA'), findsNWidgets(2)); // carte + barre
    expect(find.text('Panier vide — touchez un produit'), findsNothing);
  });

  testWidgets('PosScreen : double toucher = quantité 2 (badge ×2)',
      (tester) async {
    await _pumpPos(tester, _FakeCaisseRepo(produits: [_riz()]));
    await tester.pumpAndSettle();

    await tester.tap(find.text('Sac de riz 50kg'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Sac de riz 50kg'));
    await tester.pumpAndSettle();

    expect(find.text('2 article(s)'), findsOneWidget);
    expect(find.text('×2'), findsOneWidget);
  });

  testWidgets('PosScreen session ouverte : onglet Session affiche le rapport X',
      (tester) async {
    final rapport = RapportX(
      nbTickets: 3,
      totalTtc: 75000,
      totalTva: 11440.68,
      totalHt: 63559.32,
      panierMoyen: 25000,
      especesTheorique: 60000,
      fondCaisse: 5000,
      parMoyen: [
        MoyenTotaux(moyen: 'ESPECES', label: 'Espèces', montant: 50000, nb: 2),
        MoyenTotaux(moyen: 'TMONEY', label: 'T-Money', montant: 25000, nb: 1),
      ],
    );
    await _pumpPos(
      tester,
      _FakeCaisseRepo(
        produits: [_riz()],
        session: _sessionOuverte,
        rapport: rapport,
      ),
    );
    await tester.pumpAndSettle();

    // Pas de bandeau d'alerte quand la session est ouverte
    expect(find.text('Aucune session de caisse ouverte.'), findsNothing);

    // Onglet Session
    await tester.tap(find.text('Session'));
    await tester.pumpAndSettle();

    expect(find.text('Rapport X (à chaud)'), findsOneWidget);
    expect(find.text('75 000 FCFA'), findsWidgets);
    expect(find.text('Espèces théoriques en caisse'), findsOneWidget);
    expect(find.text('60 000 FCFA'), findsWidgets);
    expect(find.text('Clôturer la session (Z)'), findsOneWidget);
  });
}
