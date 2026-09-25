import '../../../core/network/api_client.dart';
import '../../../core/network/api_endpoints.dart';

class DashboardKpis {
  DashboardKpis({
    required this.soldeTotal,
    required this.soldeParCanal,
    required this.encaisse7j,
    required this.encaisse30j,
    required this.paiementsAValider,
    required this.nbAnomalies,
    required this.previsionJ7,
    required this.previsionJ30,
    required this.facturesEnAttente,
    required this.facturesEnRetard,
  });

  final double soldeTotal;
  final Map<String, double> soldeParCanal;
  final double encaisse7j;
  final double encaisse30j;
  final int paiementsAValider;
  final int nbAnomalies;
  final double previsionJ7;
  final double previsionJ30;
  final int facturesEnAttente;
  final int facturesEnRetard;

  factory DashboardKpis.fromJson(Map<String, dynamic> json) {
    final rawCanal = json['solde_par_canal'] as Map? ?? {};
    return DashboardKpis(
      soldeTotal: (json['solde_total'] as num?)?.toDouble() ?? 0,
      soldeParCanal: rawCanal.map((k, v) => MapEntry('$k', (v as num?)?.toDouble() ?? 0)),
      encaisse7j: (json['encaisse_7j'] as num?)?.toDouble() ?? 0,
      encaisse30j: (json['encaisse_30j'] as num?)?.toDouble() ?? 0,
      paiementsAValider: json['paiements_a_valider'] as int? ?? 0,
      nbAnomalies: json['nb_anomalies'] as int? ?? 0,
      previsionJ7: (json['prevision_j7'] as num?)?.toDouble() ?? 0,
      previsionJ30: (json['prevision_j30'] as num?)?.toDouble() ?? 0,
      facturesEnAttente: json['factures_en_attente'] as int? ?? 0,
      facturesEnRetard: json['factures_en_retard'] as int? ?? 0,
    );
  }
}

class DashboardRepository {
  DashboardRepository({ApiClient? client}) : _client = client ?? ApiClient.shared;
  final ApiClient _client;

  Future<DashboardKpis> getSummary() async {
    final resp = await _client.dio.get(ApiEndpoints.dashboard);
    return DashboardKpis.fromJson(Map<String, dynamic>.from(resp.data as Map));
  }

  Future<String> askTresoria(String question) async {
    final resp = await _client.dio.post(ApiEndpoints.assistant, data: {'question': question});
    return resp.data['answer'] as String? ?? '';
  }
}
