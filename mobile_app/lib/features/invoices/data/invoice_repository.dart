import '../../../core/network/api_client.dart';
import '../../../core/network/api_endpoints.dart';

class InvoiceItem {
  InvoiceItem({
    required this.id,
    required this.reference,
    required this.clientName,
    required this.clientPhone,
    required this.amount,
    required this.issueDate,
    required this.dueDate,
    required this.status,
    required this.statusDisplay,
  });

  final int id;
  final String reference;
  final String clientName;
  final String clientPhone;
  final double amount;
  final String issueDate;
  final String dueDate;
  final String status;
  final String statusDisplay;

  factory InvoiceItem.fromJson(Map<String, dynamic> json) {
    return InvoiceItem(
      id: json['id'] as int,
      reference: json['reference'] as String? ?? '',
      clientName: json['client_name'] as String? ?? '',
      clientPhone: json['client_phone'] as String? ?? '',
      amount: (json['amount'] as num?)?.toDouble() ?? 0,
      issueDate: json['issue_date'] as String? ?? '',
      dueDate: json['due_date'] as String? ?? '',
      status: json['status'] as String? ?? '',
      statusDisplay: json['status_display'] as String? ?? '',
    );
  }
}

class InvoiceRepository {
  InvoiceRepository({ApiClient? client}) : _client = client ?? ApiClient.shared;
  final ApiClient _client;

  /// Liste paginée DRF ({count, results}) — [status] = TOUS | EN_ATTENTE | …
  Future<List<InvoiceItem>> getInvoices({String status = 'TOUS'}) async {
    final resp = await _client.dio.get(ApiEndpoints.invoices, queryParameters: {
      if (status != 'TOUS') 'status': status,
      'page_size': 50,
    },);
    final raw = resp.data['results'] as List? ?? resp.data as List? ?? [];
    return raw.map((e) => InvoiceItem.fromJson(Map<String, dynamic>.from(e as Map))).toList();
  }
}
