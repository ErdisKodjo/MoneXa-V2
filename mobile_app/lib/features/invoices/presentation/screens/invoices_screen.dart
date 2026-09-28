import 'package:flutter/material.dart';

import '../../../../core/theme/app_colors.dart';
import '../../../../shared/utils/formatters.dart';
import '../../../../shared/widgets/status_badge.dart';
import '../../data/invoice_repository.dart';

/// Factures clients — liste filtrable par statut (API /api/invoices/).
class InvoicesScreen extends StatefulWidget {
  const InvoicesScreen({super.key, InvoiceRepository? repository})
      : _injectedRepo = repository;

  /// Injection optionnelle (tests) — null = repository réseau réel.
  final InvoiceRepository? _injectedRepo;

  @override
  State<InvoicesScreen> createState() => _InvoicesScreenState();
}

class _InvoicesScreenState extends State<InvoicesScreen> {
  late final InvoiceRepository _repo =
      widget._injectedRepo ?? InvoiceRepository();
  List<InvoiceItem> _factures = [];
  String _filtre = 'TOUS';
  bool _loading = true;
  String? _erreur;

  @override
  void initState() {
    super.initState();
    _charger();
  }

  Future<void> _charger() async {
    setState(() {
      _loading = true;
      _erreur = null;
    });
    try {
      final factures = await _repo.getInvoices(status: _filtre);
      setState(() {
        _factures = factures;
        _loading = false;
      });
    } catch (_) {
      setState(() {
        _erreur = 'Impossible de charger les factures';
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Factures')),
      body: Column(
        children: [
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            child: Row(
              children: [
                _chip('TOUS', 'Toutes'),
                _chip('EN_ATTENTE', 'En attente'),
                _chip('RECONCILIE', 'Réconciliées'),
                _chip('ANOMALIE', 'Anomalies'),
                _chip('ANNULE', 'Annulées'),
              ],
            ),
          ),
          Expanded(child: _corps()),
        ],
      ),
    );
  }

  Widget _chip(String valeur, String label) {
    final selectionne = _filtre == valeur;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 4),
      child: FilterChip(
        label: Text(label),
        selected: selectionne,
        onSelected: (_) {
          setState(() => _filtre = valeur);
          _charger();
        },
        selectedColor: AppColors.primary,
        labelStyle: TextStyle(color: selectionne ? Colors.white : AppColors.navy),
        checkmarkColor: Colors.white,
      ),
    );
  }

  Widget _corps() {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_erreur != null) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.cloud_off, size: 48, color: AppColors.muted),
            const SizedBox(height: 12),
            Text(_erreur!),
            TextButton(onPressed: _charger, child: const Text('Réessayer')),
          ],
        ),
      );
    }
    if (_factures.isEmpty) {
      return const Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.receipt_outlined, size: 48, color: AppColors.muted),
            SizedBox(height: 12),
            Text('Aucune facture', style: TextStyle(color: AppColors.muted)),
          ],
        ),
      );
    }
    return RefreshIndicator(
      onRefresh: _charger,
      child: ListView.separated(
        padding: const EdgeInsets.all(16),
        itemCount: _factures.length,
        separatorBuilder: (_, __) => const SizedBox(height: 10),
        itemBuilder: (context, index) {
          final f = _factures[index];
          return Container(
            decoration: BoxDecoration(
              color: AppColors.surface,
              borderRadius: BorderRadius.circular(16),
              border: Border.all(color: AppColors.border),
            ),
            child: ListTile(
              contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              title: Text(
                f.reference,
                style: const TextStyle(fontWeight: FontWeight.w800),
              ),
              subtitle: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(f.clientName.isEmpty ? 'Client anonyme' : f.clientName),
                  const SizedBox(height: 2),
                  Text(
                    'Émise ${Formatters.formatShortDate(f.issueDate)}'
                    ' · échéance ${Formatters.formatShortDate(f.dueDate)}',
                    style: const TextStyle(fontSize: 12, color: AppColors.muted),
                  ),
                ],
              ),
              trailing: Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Text(
                    Formatters.formatFcfa(f.amount),
                    style: const TextStyle(
                      fontWeight: FontWeight.w800,
                      color: AppColors.primary,
                    ),
                  ),
                  const SizedBox(height: 4),
                  StatusBadge(status: f.status),
                ],
              ),
            ),
          );
        },
      ),
    );
  }
}
