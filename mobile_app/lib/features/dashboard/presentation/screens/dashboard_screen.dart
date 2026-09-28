import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../../core/theme/app_colors.dart';
import '../../../../shared/utils/formatters.dart';
import '../../../../shared/widgets/kpi_card.dart';
import '../../data/dashboard_repository.dart';

class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key});

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  final _repo = DashboardRepository();
  DashboardKpis? _kpis;
  String? _error;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final kpis = await _repo.getSummary();
      setState(() {
        _kpis = kpis;
        _loading = false;
      });
    } catch (e) {
      setState(() {
        _error = 'Impossible de charger le dashboard';
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Tableau de bord')),
      body: RefreshIndicator(
        onRefresh: _load,
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : _error != null
                ? ListView(
                    children: [
                      const SizedBox(height: 80),
                      Center(child: Text(_error!)),
                    ],
                  )
                : ListView(
                    padding: const EdgeInsets.all(16),
                    children: [
                      Text(
                        Formatters.formatFcfa(_kpis!.soldeTotal),
                        style: const TextStyle(
                          fontSize: 28,
                          fontWeight: FontWeight.w800,
                          color: AppColors.primary,
                        ),
                      ),
                      const Text('Solde consolidé', style: TextStyle(color: AppColors.muted)),
                      const SizedBox(height: 16),
                      // Accès rapides — le scanner de reçu vit hors de la
                      // barre de navigation (workflow plein écran).
                      Row(
                        children: [
                          Expanded(
                            child: _ActionCard(
                              label: 'Scanner un reçu',
                              icon: Icons.document_scanner,
                              couleur: AppColors.gold,
                              onTap: () => context.push('/upload'),
                            ),
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: _ActionCard(
                              label: 'Nouvelle vente',
                              icon: Icons.point_of_sale,
                              couleur: AppColors.primary,
                              onTap: () => context.go('/caisse'),
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 16),
                      Row(
                        children: [
                          Expanded(
                            child: KpiCard(
                              label: 'Encaissé 7j',
                              value: Formatters.formatFcfa(_kpis!.encaisse7j),
                              icon: Icons.trending_up,
                              color: AppColors.success,
                            ),
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: KpiCard(
                              label: 'À valider',
                              value: '${_kpis!.paiementsAValider}',
                              icon: Icons.hourglass_empty,
                              color: AppColors.gold,
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 12),
                      Row(
                        children: [
                          Expanded(
                            child: KpiCard(
                              label: 'Anomalies',
                              value: '${_kpis!.nbAnomalies}',
                              icon: Icons.warning_amber_rounded,
                              color: AppColors.danger,
                            ),
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: KpiCard(
                              label: 'Prévision J+30',
                              value: Formatters.formatFcfa(_kpis!.previsionJ30),
                              icon: Icons.insights,
                              color: AppColors.primary,
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 24),
                      const Text(
                        'Soldes par canal',
                        style: TextStyle(fontWeight: FontWeight.w700, fontSize: 16),
                      ),
                      const SizedBox(height: 8),
                      ..._kpis!.soldeParCanal.entries.map(
                        (e) => ListTile(
                          contentPadding: EdgeInsets.zero,
                          leading: CircleAvatar(
                            backgroundColor: AppColors.channelColor(e.key).withValues(alpha: 0.15),
                            child: Icon(Icons.phone_android, color: AppColors.channelColor(e.key), size: 18),
                          ),
                          title: Text(e.key),
                          trailing: Text(
                            Formatters.formatFcfa(e.value),
                            style: const TextStyle(fontWeight: FontWeight.w700),
                          ),
                        ),
                      ),
                    ],
                  ),
      ),
    );
  }
}

/// Tuile d'accès rapide du dashboard (scan reçu, vente POS…).
class _ActionCard extends StatelessWidget {
  const _ActionCard({
    required this.label,
    required this.icon,
    required this.couleur,
    required this.onTap,
  });

  final String label;
  final IconData icon;
  final Color couleur;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: couleur.withValues(alpha: 0.1),
      borderRadius: BorderRadius.circular(14),
      child: InkWell(
        borderRadius: BorderRadius.circular(14),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
          child: Row(
            children: [
              Icon(icon, color: couleur, size: 22),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  label,
                  style: const TextStyle(
                    fontWeight: FontWeight.w700,
                    fontSize: 13,
                    color: AppColors.navy,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
