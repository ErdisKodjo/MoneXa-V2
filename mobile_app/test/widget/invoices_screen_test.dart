import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:monexa/features/invoices/data/invoice_repository.dart';
import 'package:monexa/features/invoices/presentation/screens/invoices_screen.dart';

/// Faux repository — données immédiates, zéro réseau (pas de timers pendants).
class _FakeInvoiceRepo implements InvoiceRepository {
  _FakeInvoiceRepo(this.factures);

  final List<InvoiceItem> factures;

  @override
  Future<List<InvoiceItem>> getInvoices({String status = 'TOUS'}) async {
    if (status == 'TOUS') return factures;
    return factures.where((f) => f.status == status).toList();
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

InvoiceItem _facture({
  String reference = 'FAC-2026-0001',
  String client = 'Boutique Awa',
  String status = 'EN_ATTENTE',
  double amount = 125000,
}) {
  return InvoiceItem(
    id: reference.hashCode,
    reference: reference,
    clientName: client,
    clientPhone: '+228 90 11 22 33',
    amount: amount,
    issueDate: '2026-09-01',
    dueDate: '2026-09-30',
    status: status,
    statusDisplay: 'En attente',
  );
}

void main() {
  testWidgets('InvoicesScreen : liste rendue avec référence, client, montant',
      (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: InvoicesScreen(
          repository: _FakeInvoiceRepo([
            _facture(),
            _facture(
              reference: 'FAC-2026-0002',
              client: 'Dépôt Kofi',
              status: 'RECONCILIE',
              amount: 48000,
            ),
          ]),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('FAC-2026-0001'), findsOneWidget);
    expect(find.text('Boutique Awa'), findsOneWidget);
    expect(find.text('125 000 FCFA'), findsOneWidget);
    expect(find.text('FAC-2026-0002'), findsOneWidget);
    expect(find.text('Dépôt Kofi'), findsOneWidget);
    expect(find.text('48 000 FCFA'), findsOneWidget);
  });

  testWidgets('InvoicesScreen : filtre par statut EN_ATTENTE', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: InvoicesScreen(
          repository: _FakeInvoiceRepo([
            _facture(),
            _facture(
              reference: 'FAC-2026-0002',
              client: 'Dépôt Kofi',
              status: 'RECONCILIE',
            ),
          ]),
        ),
      ),
    );
    await tester.pumpAndSettle();

    // « En attente » existe aussi comme badge de statut → cibler le chip.
    await tester.tap(find.widgetWithText(FilterChip, 'En attente'));
    await tester.pumpAndSettle();

    expect(find.text('FAC-2026-0001'), findsOneWidget);
    expect(find.text('FAC-2026-0002'), findsNothing);
  });

  testWidgets('InvoicesScreen : état vide illustré', (tester) async {
    await tester.pumpWidget(
      MaterialApp(home: InvoicesScreen(repository: _FakeInvoiceRepo([]))),
    );
    await tester.pumpAndSettle();

    expect(find.text('Aucune facture'), findsOneWidget);
    expect(find.byIcon(Icons.receipt_outlined), findsOneWidget);
  });
}
