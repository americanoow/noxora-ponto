import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

/// URL base da API. No emulador Android use 10.0.2.2; em dispositivo físico,
/// o IP da máquina na rede local:
/// `flutter run --dart-define=API_BASE_URL=http://192.168.0.10:8000`
const String apiBaseUrl = String.fromEnvironment(
  'API_BASE_URL',
  defaultValue: 'http://10.0.2.2:8000',
);

/// Em produção o tablet só conversa por HTTPS: ele envia credenciais e imagens do rosto.
bool insecureReleaseUrl(String url, {bool release = kReleaseMode}) =>
    release && !url.toLowerCase().startsWith('https://');

sealed class ApiStatus {
  const ApiStatus();
}

class ApiOk extends ApiStatus {
  const ApiOk({required this.health, required this.database});
  final String health;
  final String database;
}

class ApiError extends ApiStatus {
  const ApiError(this.message);
  final String message;
}

class ApiClient {
  ApiClient({http.Client? client, String? baseUrl})
      : _client = client ?? http.Client(),
        _baseUrl = baseUrl ?? apiBaseUrl;

  final http.Client _client;
  final String _baseUrl;

  Future<ApiStatus> fetchStatus() async {
    try {
      final health = await _get('/api/health/');
      if (health.statusCode != 200) {
        return const ApiError('O sistema não respondeu como esperado.');
      }
      final healthBody = jsonDecode(health.body);
      if (healthBody is! Map<String, dynamic> || healthBody['status'] != 'ok') {
        return const ApiError('O sistema não respondeu como esperado.');
      }
      final ready = await _get('/api/ready/');
      if (ready.statusCode != 200) {
        return const ApiError('O sistema está no ar, mas não consegue acessar os dados agora.');
      }
      final readyBody = jsonDecode(ready.body);
      if (readyBody is! Map<String, dynamic> ||
          readyBody['status'] != 'ok' || readyBody['database'] != 'ok') {
        return const ApiError('O sistema não respondeu como esperado.');
      }
      return const ApiOk(health: 'ok', database: 'ok');
    } catch (_) {
      return const ApiError('Sem conexão com o sistema.');
    }
  }

  Future<http.Response> _get(String path) =>
      _client.get(Uri.parse('$_baseUrl$path')).timeout(const Duration(seconds: 8));

  void close() => _client.close();
}
