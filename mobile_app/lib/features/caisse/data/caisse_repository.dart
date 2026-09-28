import 'dart:math';

import '../../../core/network/api_client.dart';
import '../../../core/network/api_endpoints.dart';

/// Génère un UUID v4 (clé d'idempotence POS-10) sans dépendance externe.
String generateUuidV4() {
  final rnd = Random.secure();
  final bytes = List<int>.generate(16, (_) => rnd.nextInt(256));
  bytes[6] = (bytes[6] & 0x0f) | 0x40; // version 4
  bytes[8] = (bytes[8] & 0x3f) | 0x80; // variant 10
  final hex = bytes.map((b) => b.toRadixString(16).padLeft(2, '0')).join();
  return '${hex.substring(0, 8)}-${hex.substring(8, 12)}-'
      '${hex.substring(12, 16)}-${hex.substring(16, 20)}-${hex.substring(20)}';
}

// ─────────────────────────────────────────────────────────────────────────
// Modèles
// ─────────────────────────────────────────────────────────────────────────

class CaisseProduit {
  CaisseProduit({
    required this.id,
    required this.reference,
    required this.ean,
    required this.designation,
    required this.categorieNom,
    required this.categorieCouleur,
    required this.unite,
    required this.prixTtc,
    required this.stock,
    required this.stockBas,
  });

  final int id;
  final String reference;
  final String ean;
  final String designation;
  final String categorieNom;
  final String categorieCouleur;
  final String unite;
  final double prixTtc;
  final double stock;
  final bool stockBas;

  factory CaisseProduit.fromJson(Map<String, dynamic> json) {
    return CaisseProduit(
      id: json['id'] as int,
      reference: json['reference'] as String? ?? '',
      ean: json['ean'] as String? ?? '',
      designation: json['designation'] as String? ?? '',
      categorieNom: json['categorie_nom'] as String? ?? '',
      categorieCouleur: json['categorie_couleur'] as String? ?? '#063082',
      unite: json['unite'] as String? ?? 'pièce',
      prixTtc: (json['prix_ttc'] as num?)?.toDouble() ?? 0,
      stock: (json['stock'] as num?)?.toDouble() ?? 0,
      stockBas: json['stock_bas'] as bool? ?? false,
    );
  }
}

class MoyenTotaux {
  MoyenTotaux({
    required this.moyen,
    required this.label,
    required this.montant,
    required this.nb,
  });

  final String moyen;
  final String label;
  final double montant;
  final int nb;

  factory MoyenTotaux.fromJson(Map<String, dynamic> json) {
    return MoyenTotaux(
      moyen: json['moyen'] as String? ?? '',
      label: json['label'] as String? ?? '',
      montant: (json['montant'] as num?)?.toDouble() ?? 0,
      nb: json['nb'] as int? ?? 0,
    );
  }
}

class RapportX {
  RapportX({
    required this.nbTickets,
    required this.totalTtc,
    required this.totalTva,
    required this.totalHt,
    required this.panierMoyen,
    required this.especesTheorique,
    required this.fondCaisse,
    required this.parMoyen,
  });

  final int nbTickets;
  final double totalTtc;
  final double totalTva;
  final double totalHt;
  final double panierMoyen;
  final double especesTheorique;
  final double fondCaisse;
  final List<MoyenTotaux> parMoyen;

  factory RapportX.fromJson(Map<String, dynamic> json) {
    final raw = json['par_moyen'] as List? ?? [];
    return RapportX(
      nbTickets: json['nb_tickets'] as int? ?? 0,
      totalTtc: (json['total_ttc'] as num?)?.toDouble() ?? 0,
      totalTva: (json['total_tva'] as num?)?.toDouble() ?? 0,
      totalHt: (json['total_ht'] as num?)?.toDouble() ?? 0,
      panierMoyen: (json['panier_moyen'] as num?)?.toDouble() ?? 0,
      especesTheorique: (json['especes_theorique'] as num?)?.toDouble() ?? 0,
      fondCaisse: (json['fond_caisse'] as num?)?.toDouble() ?? 0,
      parMoyen:
          raw.map((e) => MoyenTotaux.fromJson(Map<String, dynamic>.from(e as Map))).toList(),
    );
  }
}

class CaisseSession {
  CaisseSession({
    required this.id,
    required this.statut,
    required this.vendeurNom,
    required this.fondCaisse,
    required this.ouverteAt,
    this.ecart,
  });

  final int id;
  final String statut;
  final String vendeurNom;
  final double fondCaisse;
  final DateTime? ouverteAt;
  final double? ecart;

  bool get ouverte => statut == 'OUVERTE';

  factory CaisseSession.fromJson(Map<String, dynamic> json) {
    return CaisseSession(
      id: json['id'] as int,
      statut: json['statut'] as String? ?? '',
      vendeurNom: json['vendeur_nom'] as String? ?? '',
      fondCaisse: (json['fond_caisse'] as num?)?.toDouble() ?? 0,
      ouverteAt:
          json['ouverte_at'] == null ? null : DateTime.tryParse(json['ouverte_at'] as String),
      ecart: (json['ecart'] as num?)?.toDouble(),
    );
  }
}

class LigneVente {
  LigneVente({
    required this.designation,
    required this.quantite,
    required this.prixUnitaireTtc,
    required this.totalTtc,
  });

  final String designation;
  final double quantite;
  final double prixUnitaireTtc;
  final double totalTtc;

  factory LigneVente.fromJson(Map<String, dynamic> json) {
    return LigneVente(
      designation: json['designation'] as String? ?? '',
      quantite: (json['quantite'] as num?)?.toDouble() ?? 0,
      prixUnitaireTtc: (json['prix_unitaire_ttc'] as num?)?.toDouble() ?? 0,
      totalTtc: (json['total_ttc'] as num?)?.toDouble() ?? 0,
    );
  }
}

class PaiementVenteItem {
  PaiementVenteItem({
    required this.moyen,
    required this.moyenDisplay,
    required this.montant,
  });

  final String moyen;
  final String moyenDisplay;
  final double montant;

  factory PaiementVenteItem.fromJson(Map<String, dynamic> json) {
    return PaiementVenteItem(
      moyen: json['moyen'] as String? ?? '',
      moyenDisplay: json['moyen_display'] as String? ?? '',
      montant: (json['montant'] as num?)?.toDouble() ?? 0,
    );
  }
}

class VentePos {
  VentePos({
    required this.reference,
    required this.totalTtc,
    required this.statut,
    required this.statutDisplay,
    required this.vendeurNom,
    required this.clientName,
    required this.rendu,
    required this.lignes,
    required this.paiements,
    required this.createdAt,
  });

  final String reference;
  final double totalTtc;
  final String statut;
  final String statutDisplay;
  final String vendeurNom;
  final String clientName;
  final double rendu;
  final List<LigneVente> lignes;
  final List<PaiementVenteItem> paiements;
  final DateTime? createdAt;

  factory VentePos.fromJson(Map<String, dynamic> json) {
    final rawLignes = json['lignes'] as List? ?? [];
    final rawPaiements = json['paiements'] as List? ?? [];
    return VentePos(
      reference: json['reference'] as String? ?? '',
      totalTtc: (json['total_ttc'] as num?)?.toDouble() ?? 0,
      statut: json['statut'] as String? ?? '',
      statutDisplay: json['statut_display'] as String? ?? '',
      vendeurNom: json['vendeur_nom'] as String? ?? '',
      clientName: json['client_name'] as String? ?? '',
      rendu: (json['rendu'] as num?)?.toDouble() ?? 0,
      lignes:
          rawLignes.map((e) => LigneVente.fromJson(Map<String, dynamic>.from(e as Map))).toList(),
      paiements: rawPaiements
          .map((e) => PaiementVenteItem.fromJson(Map<String, dynamic>.from(e as Map)))
          .toList(),
      createdAt:
          json['created_at'] == null ? null : DateTime.tryParse(json['created_at'] as String),
    );
  }
}

class CaisseException implements Exception {
  const CaisseException(this.message);
  final String message;

  @override
  String toString() => message;
}

// ─────────────────────────────────────────────────────────────────────────
// Repository
// ─────────────────────────────────────────────────────────────────────────

class CaisseRepository {
  CaisseRepository({ApiClient? client}) : _client = client ?? ApiClient.shared;
  final ApiClient _client;

  /// Catalogue actif, recherche serveur (EAN exact, désignation, référence).
  Future<List<CaisseProduit>> getProduits({String? q}) async {
    final resp = await _client.dio.get(ApiEndpoints.caisseProduits,
        queryParameters: q == null || q.isEmpty ? null : {'q': q},);
    final raw = resp.data as List? ?? [];
    return raw.map((e) => CaisseProduit.fromJson(Map<String, dynamic>.from(e as Map))).toList();
  }

  /// Session ouverte du vendeur courant + rapport X (null si aucune).
  Future<(CaisseSession?, RapportX?)> getSession() async {
    final resp = await _client.dio.get(ApiEndpoints.caisseSession);
    final sessionJson = resp.data['session'];
    final rapportJson = resp.data['rapport'];
    return (
      sessionJson == null
          ? null
          : CaisseSession.fromJson(Map<String, dynamic>.from(sessionJson as Map)),
      rapportJson == null
          ? null
          : RapportX.fromJson(Map<String, dynamic>.from(rapportJson as Map)),
    );
  }

  Future<CaisseSession> ouvrirSession(double fondCaisse) async {
    try {
      final resp = await _client.dio.post(ApiEndpoints.caisseSession, data: {
        'fond_caisse': fondCaisse.toStringAsFixed(2),
      },);
      return CaisseSession.fromJson(Map<String, dynamic>.from(resp.data as Map));
    } catch (_) {
      throw const CaisseException(
          'Ouverture impossible — vous avez peut-être déjà une session ouverte.',);
    }
  }

  Future<CaisseSession> cloturerSession(double comptagePhysique, {String note = ''}) async {
    try {
      final resp = await _client.dio.post(ApiEndpoints.caisseCloture, data: {
        'comptage_physique': comptagePhysique.toStringAsFixed(2),
        'note': note,
      },);
      return CaisseSession.fromJson(Map<String, dynamic>.from(resp.data as Map));
    } catch (_) {
      throw const CaisseException('Clôture impossible — vérifiez la connexion.');
    }
  }

  Future<List<VentePos>> getVentes({String? statut, String? q}) async {
    final resp = await _client.dio.get(ApiEndpoints.caisseVentes, queryParameters: {
      if (statut != null && statut != 'TOUS') 'statut': statut,
      if (q != null && q.isNotEmpty) 'q': q,
    },);
    final raw = resp.data as List? ?? [];
    return raw.map((e) => VentePos.fromJson(Map<String, dynamic>.from(e as Map))).toList();
  }

  /// Encaisse une vente (idempotent côté serveur via [idempotenceKey]).
  /// Le serveur rattache automatiquement à la session ouverte du vendeur.
  Future<VentePos> enregistrerVente({
    required List<({int produitId, double quantite, double remisePct})> lignes,
    required List<({String moyen, double montant, String reference})> paiements,
    double remisePanierPct = 0,
    String clientName = '',
    String clientPhone = '',
    String? idempotenceKey,
  }) async {
    try {
      final resp = await _client.dio.post(ApiEndpoints.caisseVentes, data: {
        'lignes': [
          for (final l in lignes)
            {
              'produit_id': l.produitId,
              'quantite': l.quantite.toStringAsFixed(2),
              'remise_pct': l.remisePct.toStringAsFixed(2),
            },
        ],
        'paiements': [
          for (final p in paiements)
            {
              'moyen': p.moyen,
              'montant': p.montant.toStringAsFixed(2),
              'reference': p.reference,
            },
        ],
        'remise_panier_pct': remisePanierPct.toStringAsFixed(2),
        'client_name': clientName,
        'client_phone': clientPhone,
        'idempotence_key': idempotenceKey ?? generateUuidV4(),
      },);
      return VentePos.fromJson(Map<String, dynamic>.from(resp.data as Map));
    } catch (e) {
      // DRF renvoie {"detail": "…"} pour CaisseError — message exploitable vendeur.
      final match = RegExp(r'"detail"\s*:\s*"([^"]+)"').firstMatch(e.toString());
      throw CaisseException(
          match?.group(1) ?? 'Encaissement impossible — vérifiez la connexion et la session.',);
    }
  }
}
