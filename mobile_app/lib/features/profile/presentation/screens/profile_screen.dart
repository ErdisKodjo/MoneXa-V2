import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../../../../core/constants/app_constants.dart';
import '../../../../core/theme/app_colors.dart';
import '../../../auth/data/auth_repository.dart';
import '../../../auth/presentation/bloc/auth_bloc.dart';

class ProfileScreen extends StatelessWidget {
  const ProfileScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Profil')),
      body: BlocBuilder<AuthBloc, AuthState>(
        builder: (context, state) {
          final user = state is Authenticated ? state.user : null;
          return ListView(
            padding: const EdgeInsets.all(20),
            children: [
              CircleAvatar(
                radius: 36,
                backgroundColor: AppColors.primary,
                child: Text(
                  (user?.displayName.isNotEmpty == true ? user!.displayName[0] : 'M').toUpperCase(),
                  style: const TextStyle(color: Colors.white, fontSize: 28, fontWeight: FontWeight.w700),
                ),
              ),
              const SizedBox(height: 12),
              Text(user?.displayName ?? 'Invité', style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700)),
              Text(user?.email ?? '', style: const TextStyle(color: AppColors.muted)),
              const SizedBox(height: 8),
              Text(user?.role ?? '', style: const TextStyle(color: AppColors.primary, fontWeight: FontWeight.w600)),
              const SizedBox(height: 24),
              if (user?.role == AppConstants.roleGerant)
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('Double authentification'),
                  subtitle: Text(user!.is2faEnabled ? 'Activée' : 'Désactivée'),
                  trailing: Switch(
                    value: user.is2faEnabled,
                    onChanged: (_) async {
                      await AuthRepository().toggle2fa();
                    },
                  ),
                ),
              const ListTile(
                contentPadding: EdgeInsets.zero,
                title: Text('Langue'),
                subtitle: Text('Français / Ewé / Kabyé'),
              ),
              const SizedBox(height: 24),
              FilledButton(
                onPressed: () => context.read<AuthBloc>().add(LogoutRequestedEvent()),
                child: const Text('Se déconnecter'),
              ),
            ],
          );
        },
      ),
    );
  }
}
