import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../../../../core/constants/app_constants.dart';
import '../../../../core/theme/app_colors.dart';
import '../bloc/auth_bloc.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _emailCtrl = TextEditingController();
  final _passwordCtrl = TextEditingController();

  @override
  void dispose() {
    _emailCtrl.dispose();
    _passwordCtrl.dispose();
    super.dispose();
  }

  void _fillDemo(String email) {
    setState(() {
      _emailCtrl.text = email;
      _passwordCtrl.text = AppConstants.demoPassword;
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.cream,
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(24, 32, 24, 24),
          children: [
            const Text(
              'MoneXa',
              style: TextStyle(
                fontSize: 32,
                fontWeight: FontWeight.w800,
                color: AppColors.primary,
              ),
            ),
            const SizedBox(height: 4),
            const Text(
              'CFO virtuel pour PME ouest-africaines',
              style: TextStyle(color: AppColors.muted),
            ),
            const SizedBox(height: 28),
            const Text(
              'Connexion',
              style: TextStyle(
                fontSize: 22,
                fontWeight: FontWeight.w700,
                color: AppColors.navy,
              ),
            ),
            const SizedBox(height: 16),
            TextField(
              controller: _emailCtrl,
              keyboardType: TextInputType.emailAddress,
              decoration: const InputDecoration(
                labelText: 'Email',
                prefixIcon: Icon(Icons.mail_outline),
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _passwordCtrl,
              obscureText: true,
              decoration: const InputDecoration(
                labelText: 'Mot de passe',
                prefixIcon: Icon(Icons.lock_outline),
              ),
            ),
            const SizedBox(height: 24),
            FilledButton(
              onPressed: () {
                context.read<AuthBloc>().add(
                      LoginSubmittedEvent(
                        email: _emailCtrl.text.trim(),
                        password: _passwordCtrl.text,
                      ),
                    );
              },
              child: const Text('Se connecter'),
            ),
            const SizedBox(height: 20),
            const Text('Comptes démo', style: TextStyle(color: AppColors.muted, fontSize: 12)),
            TextButton(
              onPressed: () => _fillDemo(AppConstants.emailCaissier),
              child: const Text('Caissier'),
            ),
            TextButton(
              onPressed: () => _fillDemo(AppConstants.emailComptable),
              child: const Text('Comptable'),
            ),
            TextButton(
              onPressed: () => _fillDemo(AppConstants.emailGerant),
              child: const Text('Gérant'),
            ),
          ],
        ),
      ),
    );
  }
}
