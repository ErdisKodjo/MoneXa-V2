import 'dart:typed_data';

import 'package:dio/dio.dart';

import '../../../core/network/api_client.dart';
import '../../../core/network/api_endpoints.dart';
import '../../../core/offline/sync_queue.dart';

/// Erreur réseau non-bloquante : l'élément a été mis en file offline
/// et partira automatiquement au prochain replay (démarrage / resume).
class QueuedOfflineException implements Exception {
  QueuedOfflineException(this.message);
  final String message;
  @override
  String toString() => message;
}

class UploadRepository {
  UploadRepository({ApiClient? client}) : _injectedClient = client;

  final ApiClient? _injectedClient;
  ApiClient get _client => _injectedClient ?? ApiClient.shared;

  bool _isConnectionError(DioException e) {
    final t = e.type;
    return t == DioExceptionType.connectionTimeout ||
        t == DioExceptionType.sendTimeout ||
        t == DioExceptionType.receiveTimeout ||
        t == DioExceptionType.connectionError;
  }

  Future<Map<String, dynamic>> uploadEvidence({
    required Uint8List imageBytes,
    required String filename,
  }) async {
    final form = FormData.fromMap({
      'image': MultipartFile.fromBytes(imageBytes, filename: filename),
    });
    try {
      final resp = await _client.dio.post(ApiEndpoints.evidence, data: form);
      return Map<String, dynamic>.from(resp.data as Map);
    } on DioException catch (e) {
      if (_isConnectionError(e)) {
        // Jamais de perte de preuve : file offline + replay auto.
        await SyncQueue.instance.enqueueImage(imageBytes, filename);
        throw QueuedOfflineException(
          'Hors-ligne : le reçu a été enregistré et sera envoyé automatiquement.',
        );
      }
      rethrow;
    }
  }

  Future<Map<String, dynamic>> uploadManualText(String text) async {
    try {
      final resp = await _client.dio.post(
        ApiEndpoints.manualText,
        data: {'text': text},
      );
      return Map<String, dynamic>.from(resp.data as Map);
    } on DioException catch (e) {
      if (_isConnectionError(e)) {
        await SyncQueue.instance.enqueueText(text);
        throw QueuedOfflineException(
          'Hors-ligne : le SMS a été enregistré et sera analysé automatiquement.',
        );
      }
      rethrow;
    }
  }
}
