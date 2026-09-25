import 'dart:typed_data';

import 'package:dio/dio.dart';

import '../../../core/network/api_client.dart';
import '../../../core/network/api_endpoints.dart';

class UploadRepository {
  UploadRepository({ApiClient? client}) : _injectedClient = client;

  final ApiClient? _injectedClient;
  ApiClient get _client => _injectedClient ?? ApiClient.shared;

  Future<Map<String, dynamic>> uploadEvidence({
    required Uint8List imageBytes,
    required String filename,
  }) async {
    final form = FormData.fromMap({
      'image': MultipartFile.fromBytes(imageBytes, filename: filename),
    });
    final resp = await _client.dio.post(ApiEndpoints.evidence, data: form);
    return Map<String, dynamic>.from(resp.data as Map);
  }

  Future<Map<String, dynamic>> uploadManualText(String text) async {
    final resp = await _client.dio.post(
      ApiEndpoints.manualText,
      data: {'text': text},
    );
    return Map<String, dynamic>.from(resp.data as Map);
  }
}
