import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:monexa/features/assistant/presentation/screens/assistant_screen.dart';
import 'package:monexa/features/dashboard/data/dashboard_repository.dart';

/// Repository factice : échec immédiat, déterministe (aucune socket réseau,
/// aucun timer de timeout Dio en attente) — le flux de secours est identique
/// à une erreur réseau réelle.
class _FailingRepo extends DashboardRepository {
  @override
  Future<String> askTresoria(String question) async {
    throw StateError('Test : réseau désactivé (repo factice)');
  }
}

void main() {
  group('AssistantScreen (TresorIA) tests', () {
    testWidgets('affiche le message de bienvenue, les suggestions et le champ de saisie',
        (tester) async {
      await tester.pumpWidget(const MaterialApp(home: AssistantScreen()));
      await tester.pumpAndSettle(const Duration(seconds: 1));

      // Message de bienvenue du bot
      expect(find.textContaining('TresorIA'), findsWidgets);
      // Champ de saisie
      expect(find.text('Posez votre question…'), findsOneWidget);
      // Bouton d'envoi
      expect(find.byIcon(Icons.send), findsOneWidget);
      // Suggestions visibles (aucun message échangé)
      expect(find.text('Combien ai-je en T-Money ?'), findsOneWidget);
    });

    testWidgets('envoie une question et affiche la bulle utilisateur', (tester) async {
      // Repository factice injecté : l'erreur immédiate produit la bulle de
      // secours — ce test vérifie le flux UI local sans toucher au réseau.
      await tester.pumpWidget(
        MaterialApp(home: AssistantScreen(repo: _FailingRepo())),
      );
      await tester.pumpAndSettle(const Duration(seconds: 1));

      await tester.enterText(find.byType(TextField), 'Test question démo');
      await tester.tap(find.byIcon(Icons.send));
      await tester.pump(); // bulle user immédiate

      expect(find.text('Test question démo'), findsOneWidget);
    });
  });
}
