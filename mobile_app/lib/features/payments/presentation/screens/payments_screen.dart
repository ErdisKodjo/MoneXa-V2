import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../../../../core/theme/app_colors.dart';
import '../../../../shared/utils/formatters.dart';
import '../../../../shared/widgets/status_badge.dart';
import '../../data/payment_repository.dart';
import '../bloc/payments_bloc.dart';

class PaymentsScreen extends StatefulWidget {
  const PaymentsScreen({super.key});

  @override
  State<PaymentsScreen> createState() => _PaymentsScreenState();
}

class _PaymentsScreenState extends State<PaymentsScreen> {
  String _filter = 'TOUS';

  @override
  void initState() {
    super.initState();
    context.read<PaymentsBloc>().add(LoadPaymentsEvent(status: _filter));
  }

  void _setFilter(String status) {
    setState(() => _filter = status);
    context.read<PaymentsBloc>().add(LoadPaymentsEvent(status: status));
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Paiements')),
      body: Column(
        children: [
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            child: Row(
              children: [
                _chip('TOUS', 'Tous'),
                _chip('A_VALIDER', 'À valider'),
                _chip('RECONCILIE', 'Réconciliés'),
                _chip('ANOMALIE', 'Anomalies'),
              ],
            ),
          ),
          Expanded(
            child: BlocBuilder<PaymentsBloc, PaymentsState>(
              builder: (context, state) {
                if (state is PaymentsLoading || state is PaymentsInitial) {
                  return const Center(child: CircularProgressIndicator());
                }
                if (state is PaymentsFailure) {
                  return Center(child: Text(state.message));
                }
                final payments = state is PaymentsLoaded ? state.payments : <PaymentItem>[];
                if (payments.isEmpty) {
                  return const Center(child: Text('Aucun paiement'));
                }
                return RefreshIndicator(
                  onRefresh: () async {
                    context.read<PaymentsBloc>().add(LoadPaymentsEvent(status: _filter));
                  },
                  child: ListView.separated(
                    padding: const EdgeInsets.all(16),
                    itemCount: payments.length,
                    separatorBuilder: (_, __) => const SizedBox(height: 10),
                    itemBuilder: (context, index) {
                      final p = payments[index];
                      return Container(
                        padding: const EdgeInsets.all(16),
                        decoration: BoxDecoration(
                          color: Colors.white,
                          borderRadius: BorderRadius.circular(16),
                          border: Border.all(color: AppColors.border),
                        ),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              children: [
                                StatusBadge(status: p.channel, isChannel: true),
                                const Spacer(),
                                StatusBadge(status: p.status),
                              ],
                            ),
                            const SizedBox(height: 8),
                            Text(
                              Formatters.formatFcfa(p.amount),
                              style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 18),
                            ),
                            Text(p.payerName, style: const TextStyle(color: AppColors.navy)),
                            Text(p.providerRef, style: const TextStyle(color: AppColors.muted, fontSize: 12)),
                            Text(Formatters.formatShortDate(p.paidAt), style: const TextStyle(fontSize: 12, color: AppColors.muted)),
                            if (p.status == 'A_VALIDER') ...[
                              const SizedBox(height: 8),
                              Row(
                                children: [
                                  TextButton(
                                    onPressed: () => context.read<PaymentsBloc>().add(
                                          ValidatePaymentActionSubmittedEvent(
                                            paymentId: p.id,
                                            action: 'APPROVE',
                                            currentFilterStatus: _filter,
                                          ),
                                        ),
                                    child: const Text('Valider'),
                                  ),
                                  TextButton(
                                    onPressed: () => context.read<PaymentsBloc>().add(
                                          ValidatePaymentActionSubmittedEvent(
                                            paymentId: p.id,
                                            action: 'REJECT',
                                            currentFilterStatus: _filter,
                                          ),
                                        ),
                                    child: const Text('Rejeter', style: TextStyle(color: AppColors.danger)),
                                  ),
                                ],
                              ),
                            ],
                          ],
                        ),
                      );
                    },
                  ),
                );
              },
            ),
          ),
        ],
      ),
    );
  }

  Widget _chip(String value, String label) {
    final selected = _filter == value;
    return Padding(
      padding: const EdgeInsets.only(right: 8),
      child: ChoiceChip(
        label: Text(label),
        selected: selected,
        onSelected: (_) => _setFilter(value),
      ),
    );
  }
}
