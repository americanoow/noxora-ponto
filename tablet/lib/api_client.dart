import 'dart:convert';

import 'package:http/http.dart' as http;

/// URL base da API. No emulador Android use 10.0.2.2; em dispositivo físico,
/// o IP da máquina na rede local:
/// `flutter run --dart-define=API_BASE_URL=http://192.168.0.10:8000`
const String apiBaseUrl = String.fromEnvironment(
  'API_BASE_URL',
  defaultValue: 'http://10.0.2.2:8000',
);

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
        return const ApiError('A API não respondeu corretamente.');
      }
      final ready = await _get('/api/ready/');
      if (ready.statusCode != 200) {
        return const ApiError('A API está no ar, mas o banco está indisponível.');
      }
      return ApiOk(
        health: '${jsonDecode(health.body)['status']}',
        database: '${jsonDecode(ready.body)['database']}',
      );
    } catch (_) {
      return const ApiError('Não foi possível contatar a API.');
    }
  }

  Future<http.Response> _get(String path) =>
      _client.get(Uri.parse('$_baseUrl$path')).timeout(const Duration(seconds: 8));
}
