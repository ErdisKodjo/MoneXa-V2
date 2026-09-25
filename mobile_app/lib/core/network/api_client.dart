import 'package:dio/dio.dart';

import '../constants/app_constants.dart';
import 'api_endpoints.dart';

class ApiClient {
  ApiClient({
    Dio? dio,
    Future<String?> Function()? readAccess,
    Future<String?> Function()? readRefresh,
    Future<void> Function(String access, String? refresh)? saveTokens,
  })  : _readAccess = readAccess,
        _readRefresh = readRefresh,
        _saveTokens = saveTokens,
        dio = dio ??
            Dio(
              BaseOptions(
                baseUrl: AppConstants.apiBaseUrl,
                connectTimeout: const Duration(seconds: 20),
                receiveTimeout: const Duration(seconds: 30),
                headers: {'Accept': 'application/json'},
              ),
            ) {
    final client = this.dio;
    client.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) async {
          final token = await _readAccess?.call();
          if (token != null && token.isNotEmpty) {
            options.headers['Authorization'] = 'Bearer $token';
          }
          handler.next(options);
        },
        onError: (error, handler) async {
          if (error.response?.statusCode == 401) {
            final refreshed = await _refreshToken();
            if (refreshed) {
              final token = await _readAccess?.call();
              final req = error.requestOptions;
              req.headers['Authorization'] = 'Bearer $token';
              try {
                final clone = await client.fetch(req);
                return handler.resolve(clone);
              } catch (_) {}
            }
          }
          handler.next(error);
        },
      ),
    );
  }

  static ApiClient? _shared;
  static ApiClient get shared => _shared ?? (_shared = ApiClient());
  static void configure(ApiClient client) => _shared = client;

  final Dio dio;
  final Future<String?> Function()? _readAccess;
  final Future<String?> Function()? _readRefresh;
  final Future<void> Function(String access, String? refresh)? _saveTokens;

  Future<bool> _refreshToken() async {
    final refresh = await _readRefresh?.call();
    if (refresh == null || refresh.isEmpty) return false;
    try {
      final response = await Dio(
        BaseOptions(baseUrl: AppConstants.apiBaseUrl),
      ).post(ApiEndpoints.refresh, data: {'refresh': refresh});
      final access = response.data['access'] as String?;
      if (access == null) return false;
      await _saveTokens?.call(access, response.data['refresh'] as String?);
      return true;
    } catch (_) {
      return false;
    }
  }
}
