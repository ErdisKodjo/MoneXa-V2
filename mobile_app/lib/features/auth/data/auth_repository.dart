import 'dart:convert';

import 'package:dio/dio.dart';

import '../../../core/network/api_client.dart';
import '../../../core/network/api_endpoints.dart';
import 'token_store.dart';

class UserModel {
  UserModel({
    required this.id,
    required this.email,
    required this.role,
    required this.displayName,
    this.phone = '',
    this.is2faEnabled = false,
  });

  final int id;
  final String email;
  final String role;
  final String displayName;
  final String phone;
  final bool is2faEnabled;

  factory UserModel.fromJson(Map<String, dynamic> json) {
    return UserModel(
      id: json['id'] as int? ?? 0,
      email: json['email'] as String? ?? '',
      role: json['role'] as String? ?? '',
      displayName: json['display_name'] as String? ?? json['email'] as String? ?? '',
      phone: json['phone'] as String? ?? '',
      is2faEnabled: json['is_2fa_enabled'] as bool? ?? false,
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'email': email,
        'role': role,
        'display_name': displayName,
        'phone': phone,
        'is_2fa_enabled': is2faEnabled,
      };
}

class AuthRepository {
  AuthRepository({
    ApiClient? client,
    TokenStore? storage,
  })  : _injectedClient = client,
        _storage = storage ?? MemoryTokenStore();

  final ApiClient? _injectedClient;
  final TokenStore _storage;

  ApiClient get _client => _injectedClient ?? ApiClient.shared;

  Future<UserModel> login({required String email, required String password}) async {
    try {
      final tokenResp = await _client.dio.post(
        ApiEndpoints.token,
        data: {'email': email, 'password': password},
      );
      final access = tokenResp.data['access'] as String?;
      final refresh = tokenResp.data['refresh'] as String?;
      if (access == null) {
        throw Exception('Identifiants invalides');
      }
      await _storage.write('access', access);
      if (refresh != null) {
        await _storage.write('refresh', refresh);
      }
      final meResp = await _client.dio.get(ApiEndpoints.me);
      final user = UserModel.fromJson(Map<String, dynamic>.from(meResp.data as Map));
      await _storage.write('user', jsonEncode(user.toJson()));
      return user;
    } on DioException catch (e) {
      if (e.response?.statusCode == 401) {
        throw Exception('Identifiants invalides');
      }
      throw Exception(e.message ?? 'Erreur de connexion');
    }
  }

  Future<UserModel?> getStoredUser() async {
    final raw = await _storage.read('user');
    final access = await _storage.read('access');
    if (raw == null || access == null) return null;
    return UserModel.fromJson(jsonDecode(raw) as Map<String, dynamic>);
  }

  Future<void> logout() async {
    await _storage.deleteAll();
  }

  Future<bool> toggle2fa() async {
    final resp = await _client.dio.patch(ApiEndpoints.toggle2fa);
    return resp.data['is_2fa_enabled'] as bool? ?? false;
  }
}
