import '../../../core/network/api_client.dart';
import '../../../core/network/api_endpoints.dart';

class PaymentItem {
  PaymentItem({
    required this.id,
    required this.providerRef,
    required this.amount,
    required this.channel,
    required this.payerName,
    required this.payerPhone,
    required this.paidAt,
    required this.status,
    required this.matchMethod,
    required this.aiConfidence,
    this.invoiceRef,
  });

  final int id;
  final String providerRef;
  final double amount;
  final String channel;
  final String payerName;
  final String payerPhone;
  final String paidAt;
  final String status;
  final String matchMethod;
  final double aiConfidence;
  final String? invoiceRef;

  factory PaymentItem.fromJson(Map<String, dynamic> json) {
    return PaymentItem(
      id: json['id'] as int? ?? 0,
      providerRef: json['provider_ref'] as String? ?? '',
      amount: double.tryParse('${json['amount']}') ?? 0,
      channel: json['channel'] as String? ?? '',
      payerName: json['payer_name'] as String? ?? '',
      payerPhone: json['payer_phone'] as String? ?? '',
      paidAt: json['paid_at'] as String? ?? '',
      status: json['status'] as String? ?? '',
      matchMethod: json['match_method'] as String? ?? '',
      aiConfidence: double.tryParse('${json['ai_confidence']}') ?? 0,
      invoiceRef: json['invoice_reference'] as String? ?? json['invoiceRef'] as String?,
    );
  }
}

class PaymentRepository {
  PaymentRepository({ApiClient? client}) : _injectedClient = client;

  final ApiClient? _injectedClient;
  ApiClient get _client => _injectedClient ?? ApiClient.shared;

  Future<List<PaymentItem>> getPayments({String? status}) async {
    final query = <String, dynamic>{};
    if (status != null && status != 'TOUS') {
      query['status'] = status;
    }
    final resp = await _client.dio.get(ApiEndpoints.payments, queryParameters: query);
    final data = resp.data;
    final List list;
    if (data is Map && data['results'] is List) {
      list = data['results'] as List;
    } else if (data is List) {
      list = data;
    } else {
      list = const [];
    }
    return list
        .map((e) => PaymentItem.fromJson(Map<String, dynamic>.from(e as Map)))
        .toList();
  }

  Future<void> validatePayment(int paymentId, {required String action}) async {
    await _client.dio.patch(
      ApiEndpoints.validatePayment(paymentId),
      data: {'action': action, 'decision': action == 'APPROVE' ? 'RECONCILIE' : 'ANOMALIE'},
    );
  }
}
