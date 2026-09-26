import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:monexa/features/auth/data/auth_repository.dart';
import 'package:monexa/features/auth/presentation/bloc/auth_bloc.dart';
import 'package:monexa/features/auth/presentation/screens/login_screen.dart';

class MockAuthRepository extends AuthRepository {
  @override
  Future<UserModel?> getStoredUser() async => null;
}

void main() {
  testWidgets('LoginScreen renders brand, inputs, and demo chips correctly', (tester) async {
    final authBloc = AuthBloc(repository: MockAuthRepository());

    await tester.pumpWidget(
      MaterialApp(
        home: BlocProvider<AuthBloc>.value(
          value: authBloc,
          child: const LoginScreen(),
        ),
      ),
    );

    // Vérifie le logo et les titres
    expect(find.text('MoneXa'), findsOneWidget);
    expect(find.text('Connexion'), findsOneWidget);
    expect(find.text('Se connecter'), findsOneWidget);

    // Vérifie les 3 boutons de démonstration rapide Hackathon
    expect(find.text('Caissier'), findsOneWidget);
    expect(find.text('Comptable'), findsOneWidget);
    expect(find.text('Gérant'), findsOneWidget);

    // Taper sur le bouton Gérant doit préremplir l'email
    await tester.tap(find.text('Gérant'));
    await tester.pump();

    expect(find.text('gerant@monexa.tg'), findsOneWidget);

    await authBloc.close();
  });
}
