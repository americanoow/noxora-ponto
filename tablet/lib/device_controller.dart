import 'dart:convert';
import 'dart:math';

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

/// Resultado de uma tentativa de marcação.
sealed class PunchOutcome {
  const PunchOutcome();
}

/// Marcação gravada pelo servidor (ou reenvio de uma já gravada: [duplicate]).
class PunchRecorded extends PunchOutcome {
  const PunchRecorded({
    required this.nsr,
    required this.workerName,
    required this.occurredAt,
    required this.hash,
    required this.duplicate,
  });
  final int nsr;
  final String workerName;
  final String occurredAt;
  final String hash;
  final bool duplicate;
}

/// Recusa definitiva (matrícula inválida etc.): nada foi gravado e a tentativa se encerra.
class PunchRejected extends PunchOutcome {
  const PunchRejected(this.message);
  final String message;
}

/// Sem confirmação do servidor: a marcação pode ou não ter sido gravada. A próxima tentativa com
/// a mesma matrícula reutiliza o mesmo identificador de evento, então não duplica.
class PunchUnconfirmed extends PunchOutcome {
  const PunchUnconfirmed(this.message);
  final String message;
}

String _newEventId() {
  final random = Random.secure();
  final bytes = List<int>.generate(16, (_) => random.nextInt(256));
  bytes[6] = (bytes[6] & 0x0f) | 0x40; // versão 4
  bytes[8] = (bytes[8] & 0x3f) | 0x80; // variante RFC 4122
  final hex = bytes.map((b) => b.toRadixString(16).padLeft(2, '0')).join();
  return '${hex.substring(0, 8)}-${hex.substring(8, 12)}-${hex.substring(12, 16)}-'
      '${hex.substring(16, 20)}-${hex.substring(20)}';
}

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
  Future<void>? _operation;
  bool _disposed = false;

  DeviceState state = DeviceState.loading;
  DeviceScope? scope;
  String? message;

  Future<void> init() => heartbeat();

  // Heartbeat, ativação e rotação nunca alteram o armazenamento em paralelo.
  Future<void> _exclusive(Future<void> Function() action) {
    if (_disposed) return Future<void>.value();
    return _operation ??= Future<void>.microtask(action).whenComplete(() => _operation = null);
  }

  Future<void> activate(String code) => _exclusive(() => _activate(code));

  Future<void> _activate(String code) async {
    message = null;
    _set(DeviceState.loading);
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
        final nextScope = DeviceScope.fromJson(body);
        final token = body['token'] as String;
        if (token.isEmpty) throw const FormatException('Credencial vazia.');
        await store.write(StoredCredential(token: token, issuedAt: _now()));
        scope = nextScope;
        _set(DeviceState.active);
      } else if (response.statusCode == 429) {
        _set(DeviceState.unactivated, 'Muitas tentativas. Aguarde um minuto.');
      } else {
        _set(DeviceState.unactivated, 'Código inválido ou expirado.');
      }
    } catch (_) {
      _set(DeviceState.unactivated, 'Não foi possível concluir a ativação. Verifique a conexão e o armazenamento seguro.');
    }
  }

  Future<void> heartbeat() => _exclusive(_heartbeat);

  Future<void> _heartbeat() async {
    try {
      final credential = await store.read();
      if (credential == null) {
        _set(DeviceState.unactivated);
        return;
      }
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
        scope = null;
        _set(DeviceState.revoked, 'Este tablet foi desativado. Peça um novo código de ativação.');
        await store.clear();
      } else if (response.statusCode == 403) {
        // Empresa suspensa: mantém a credencial, que volta a valer quando o acesso for restabelecido.
        _set(DeviceState.offline, 'Acesso suspenso. Procure o administrador.');
      } else {
        _set(DeviceState.offline, 'Servidor indisponível. Tentaremos novamente.');
      }
    } catch (_) {
      _set(DeviceState.offline, 'Não foi possível verificar o acesso ou ler a credencial segura.');
    }
  }

  Future<void> _rotate(StoredCredential current) async {
    try {
      final response = await _client
          .post(Uri.parse('$_baseUrl/api/device/rotate-credential/'), headers: _headers(current.token))
          .timeout(const Duration(seconds: 10));
      if (response.statusCode == 200) {
        final body = jsonDecode(response.body) as Map<String, dynamic>;
        final token = body['token'] as String;
        if (token.isEmpty) throw const FormatException('Credencial vazia.');
        await store.write(StoredCredential(token: token, issuedAt: _now()));
      } else if (response.statusCode == 401) {
        scope = null;
        _set(DeviceState.revoked, 'Este tablet foi desativado. Peça um novo código de ativação.');
        await store.clear();
      } else if (response.statusCode == 403) {
        _set(DeviceState.offline, 'Acesso suspenso. Procure o administrador.');
      }
    } catch (_) {
      // Mantém a credencial atual; nova tentativa no próximo heartbeat.
    }
  }

  // Tentativa em aberto (sem resposta definitiva): preserva o evento para o reenvio ser idempotente.
  final Map<String, Map<String, dynamic>> _pendingPunches = {};
  bool _punching = false;

  /// Registra uma marcação. [declaredKind]: '', 'entry', 'break_start', 'break_end' ou 'exit'
  /// (informativo; a apuração decide). Nunca grava localmente: a fila offline é da etapa 7.
  Future<PunchOutcome> punch(String registration, {String declaredKind = ''}) async {
    final reg = registration.trim();
    if (reg.isEmpty) return const PunchRejected('Informe a matrícula.');
    if (_punching) return const PunchUnconfirmed('Aguarde a conclusão do registro anterior.');
    _punching = true;
    final wasUnconfirmed = _pendingPunches.containsKey(reg);
    try {
      final credential = await store.read();
      if (credential == null) {
        return wasUnconfirmed
            ? const PunchUnconfirmed('Tentativa anterior sem confirmação. Procure o administrador.')
            : const PunchRejected('Tablet não ativado.');
      }
      final payload = _pendingPunches.putIfAbsent(reg, () => {
        'registration': reg,
        'client_event_id': _newEventId(),
        'declared_kind': declaredKind,
        'device_reported_at': _now().toUtc().toIso8601String(),
      });
      final response = await _client
          .post(
            Uri.parse('$_baseUrl/api/device/punches/'),
            headers: _headers(credential.token),
            body: jsonEncode(payload),
          )
          .timeout(const Duration(seconds: 10));
      if (response.statusCode == 200 || response.statusCode == 201) {
        final body = jsonDecode(response.body) as Map<String, dynamic>;
        final receipt = body['receipt'] as Map<String, dynamic>;
        final outcome = PunchRecorded(
          nsr: (receipt['nsr'] as num).toInt(),
          workerName: '${(receipt['worker'] as Map<String, dynamic>)['name']}',
          occurredAt: '${receipt['occurred_at']}',
          hash: '${receipt['hash_sha256']}',
          duplicate: body['duplicate'] == true,
        );
        _pendingPunches.remove(reg);
        return outcome;
      }
      if (response.statusCode == 401) {
        // A recusa atual não prova que uma tentativa anterior não foi gravada.
        if (!wasUnconfirmed) _pendingPunches.remove(reg);
        scope = null;
        _set(DeviceState.revoked, 'Este tablet foi desativado. Peça um novo código de ativação.');
        await store.clear();
        if (wasUnconfirmed) {
          return const PunchUnconfirmed('Tablet desativado. Tentativa anterior sem confirmação. Procure o administrador.');
        }
        return const PunchRejected('Tablet desativado. Marcação não registrada.');
      }
      if (response.statusCode == 404 || response.statusCode == 400) {
        if (!wasUnconfirmed) _pendingPunches.remove(reg);
        if (wasUnconfirmed) {
          return const PunchUnconfirmed('Tentativa anterior sem confirmação. Procure o administrador.');
        }
        return PunchRejected(response.statusCode == 404
            ? 'Matrícula não encontrada nesta unidade. Marcação não registrada.'
            : 'Dados ou identificação recusados. Marcação não registrada.');
      }
      return const PunchUnconfirmed('Servidor indisponível. Tente novamente: não haverá duplicidade.');
    } catch (_) {
      return const PunchUnconfirmed('Sem confirmação do servidor. Tente novamente: não haverá duplicidade.');
    } finally {
      _punching = false;
    }
  }

  Map<String, String> _headers(String token) =>
      {'Content-Type': 'application/json', 'Authorization': 'Device $token'};

  void _set(DeviceState next, [String? text]) {
    if (_disposed) return;
    state = next;
    message = text;
    notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _client.close();
    super.dispose();
  }
}
