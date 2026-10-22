import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import 'api_client.dart' show apiBaseUrl;
import 'token_store.dart';

/// Versão informada ao servidor (heartbeat). Mantida em sincronia com o pubspec.
const String appVersion = '0.1.0';

/// Quando a credencial passa desta idade, o tablet pede uma nova (a do servidor vale 30 dias).
const Duration rotateAfter = Duration(days: 20);

class DeviceScope {
  const DeviceScope({required this.name, required this.company, required this.unit});
  final String name;
  final String company;
  final String unit;

  factory DeviceScope.fromJson(Map<String, dynamic> json) => DeviceScope(
        name: '${json['name']}',
        company: '${(json['company'] as Map<String, dynamic>)['name']}',
        unit: '${(json['unit'] as Map<String, dynamic>)['name']}',
      );
}

enum DeviceState { loading, unactivated, active, revoked, offline }

/// Ciclo de vida do tablet: ativação, heartbeat, rotação e tratamento de revogação.
///
/// Limitação conhecida (etapa 7): sem rede o servidor não consegue revogar; o acesso offline
/// só é limitado pela validade da credencial.
class DeviceController extends ChangeNotifier {
  DeviceController({required this.store, http.Client? client, String? baseUrl, DateTime Function()? now})
      : _client = client ?? http.Client(),
        _baseUrl = baseUrl ?? apiBaseUrl,
        _now = now ?? DateTime.now;

  final TokenStore store;
  final http.Client _client;
  final String _baseUrl;
  final DateTime Function() _now;

  DeviceState state = DeviceState.loading;
  DeviceScope? scope;
  String? message;

  Future<void> init() async {
    final credential = await store.read();
    if (credential == null) {
      _set(DeviceState.unactivated);
      return;
    }
    await heartbeat();
  }

  Future<void> activate(String code) async {
    message = null;
    try {
      final response = await _client
          .post(
            Uri.parse('$_baseUrl/api/device/activate/'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({'code': code, 'app_version': appVersion}),
          )
          .timeout(const Duration(seconds: 10));
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      if (response.statusCode == 201) {
        await store.write(StoredCredential(token: '${body['token']}', issuedAt: _now()));
        scope = DeviceScope.fromJson(body);
        _set(DeviceState.active);
      } else if (response.statusCode == 429) {
        _set(DeviceState.unactivated, 'Muitas tentativas. Aguarde um minuto.');
      } else {
        _set(DeviceState.unactivated, 'Código inválido ou expirado.');
      }
    } catch (_) {
      _set(DeviceState.unactivated, 'Não foi possível contatar o servidor.');
    }
  }

  Future<void> heartbeat() async {
    final credential = await store.read();
    if (credential == null) {
      _set(DeviceState.unactivated);
      return;
    }
    try {
      final response = await _client
          .post(
            Uri.parse('$_baseUrl/api/device/heartbeat/'),
            headers: _headers(credential.token),
            body: jsonEncode({'app_version': appVersion}),
          )
          .timeout(const Duration(seconds: 10));
      if (response.statusCode == 200) {
        scope = DeviceScope.fromJson(jsonDecode(response.body) as Map<String, dynamic>);
        _set(DeviceState.active);
        if (_now().difference(credential.issuedAt) > rotateAfter) await _rotate(credential);
      } else if (response.statusCode == 401) {
        // Revogado ou expirado: a credencial local não serve mais.
        await store.clear();
        scope = null;
        _set(DeviceState.revoked, 'Este tablet foi desativado. Peça um novo código de ativação.');
      } else if (response.statusCode == 403) {
        // Empresa suspensa: mantém a credencial, que volta a valer quando o acesso for restabelecido.
        _set(DeviceState.offline, 'Acesso suspenso para esta empresa. Procure o administrador.');
      } else {
        _set(DeviceState.offline, 'Servidor indisponível. Tentaremos novamente.');
      }
    } catch (_) {
      _set(DeviceState.offline, 'Sem conexão com o servidor.');
    }
  }

  Future<void> _rotate(StoredCredential current) async {
    try {
      final response = await _client
          .post(Uri.parse('$_baseUrl/api/device/rotate-credential/'), headers: _headers(current.token))
          .timeout(const Duration(seconds: 10));
      if (response.statusCode == 200) {
        final body = jsonDecode(response.body) as Map<String, dynamic>;
        await store.write(StoredCredential(token: '${body['token']}', issuedAt: _now()));
      }
    } catch (_) {
      // Mantém a credencial atual; nova tentativa no próximo heartbeat.
    }
  }

  Map<String, String> _headers(String token) =>
      {'Content-Type': 'application/json', 'Authorization': 'Device $token'};

  void _set(DeviceState next, [String? text]) {
    state = next;
    message = text;
    notifyListeners();
  }
}
