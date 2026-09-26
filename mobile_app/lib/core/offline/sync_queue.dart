import 'dart:typed_data';

import 'package:hive_flutter/hive_flutter.dart';

/// File de synchronisation hors-ligne (v2.1).
///
/// Objectif (pilier « accessibilité mobile ») : un reçu photographié ou un
/// SMS collé sans réseau n'est JAMAIS perdu. Il est mis en file dans une box
/// Hive dédiée puis rejoué automatiquement dès que le backend redevient
/// joignable (démarrage de l'app, retour au premier plan).
///
/// Fonctionnement :
/// 1. `enqueue*()` persiste l'élément (clé UUID locale).
/// 2. `replayAll()` tente chaque élément dans l'ordre chronologique :
///    - succès   → l'entrée est supprimée de la file ;
///    - échec    → `retries` est incrémenté (abandon après 5 tentatives).
/// 3. L'UI peut écouter `pendingCount` (ValueListenable) pour afficher un
///    badge « N reçus en attente de synchronisation ».
class PendingUpload {
  PendingUpload({
    required this.id,
    required this.kind,
    required this.createdAt,
    this.imageBytes,
    this.filename,
    this.text,
    this.retries = 0,
  });

  final String id;
  final String kind; // 'image' | 'text'
  final DateTime createdAt;
  final Uint8List? imageBytes;
  final String? filename;
  final String? text;
  int retries;

  Map<String, dynamic> toMap() => {
        'id': id,
        'kind': kind,
        'createdAt': createdAt.toIso8601String(),
        'imageBytes': imageBytes,
        'filename': filename,
        'text': text,
        'retries': retries,
      };

  static PendingUpload fromMap(Map<dynamic, dynamic> map) {
    final dynamic bytes = map['imageBytes'];
    return PendingUpload(
      id: map['id'] as String,
      kind: map['kind'] as String,
      createdAt: DateTime.tryParse(map['createdAt'] as String? ?? '') ??
          DateTime.now(),
      imageBytes: bytes is Uint8List ? bytes : null,
      filename: map['filename'] as String?,
      text: map['text'] as String?,
      retries: (map['retries'] as num?)?.toInt() ?? 0,
    );
  }
}

class SyncQueue {
  SyncQueue._();
  static final SyncQueue instance = SyncQueue._();

  static const String _boxName = 'pending_uploads';
  static const int maxRetries = 5;

  Box? _box;

  Future<void> init() async {
    _box ??= await Hive.openBox(_boxName);
  }

  Box get _requireBox =>
      _box ?? (throw StateError('SyncQueue.init() doit être appelé au startup'));

  /// Nombre d'éléments en attente — pour le badge UI.
  int get pendingCount => _box?.length ?? 0;

  String _newId() =>
      'pu-${DateTime.now().microsecondsSinceEpoch}-$pendingCount';

  Future<void> enqueueImage(Uint8List bytes, String filename) async {
    await init();
    final item = PendingUpload(
      id: _newId(),
      kind: 'image',
      createdAt: DateTime.now(),
      imageBytes: bytes,
      filename: filename,
    );
    await _requireBox.put(item.id, item.toMap());
  }

  Future<void> enqueueText(String text) async {
    await init();
    final item = PendingUpload(
      id: _newId(),
      kind: 'text',
      createdAt: DateTime.now(),
      text: text,
    );
    await _requireBox.put(item.id, item.toMap());
  }

  /// Rejoue la file avec la fonction d'envoi fournie.
  ///
  /// [sendImage] et [sendText] lèvent une exception si le réseau est
  /// indisponible — l'élément reste alors en file (retry au prochain passage).
  Future<SyncResult> replayAll({
    required Future<void> Function(Uint8List bytes, String filename) sendImage,
    required Future<void> Function(String text) sendText,
  }) async {
    await init();
    int sent = 0;
    int failed = 0;
    final keys = _requireBox.keys.toList();
    for (final key in keys) {
      final raw = _requireBox.get(key);
      if (raw == null) continue;
      final item = PendingUpload.fromMap(Map<dynamic, dynamic>.from(raw as Map));
      try {
        if (item.kind == 'image' && item.imageBytes != null) {
          await sendImage(item.imageBytes!, item.filename ?? 'receipt.jpg');
        } else if (item.kind == 'text' && item.text != null) {
          await sendText(item.text!);
        } else {
          // Entrée corrompue : on la retire pour ne pas bloquer la file.
          await _requireBox.delete(key);
          continue;
        }
        await _requireBox.delete(key);
        sent++;
      } catch (_) {
        failed++;
        item.retries += 1;
        if (item.retries >= maxRetries) {
          // Abandon définitif : l'entrée est retirée après 5 échecs.
          await _requireBox.delete(key);
        } else {
          await _requireBox.put(key, item.toMap());
        }
      }
    }
    return SyncResult(sent: sent, failed: failed, pending: pendingCount);
  }
}

class SyncResult {
  SyncResult({required this.sent, required this.failed, required this.pending});

  final int sent;
  final int failed;
  final int pending;

  @override
  String toString() =>
      'SyncResult(sent: $sent, failed: $failed, pending: $pending)';
}
