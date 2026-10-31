import 'dart:convert';
import 'dart:math';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import 'api_client.dart' show apiBaseUrl;
import 'offline_queue.dart';
import 'token_store.dart';

/// Versão informada ao servidor (heartbeat). Mantida em sincronia com o pubspec.
const String appVersion = '0.1.0';

/// Quando a credencial passa desta idade, o tablet pede uma nova (a do servidor vale 30 dias).
const Duration rotateAfter = Duration(days: 20);

class DeviceScope {
  const DeviceScope({
    required this.name,
    required this.company,
    required this.unit,
    this.deviceId,
    this.companyId,
    this.identificationMode = 'registration',
    this.offlinePolicy = 'disabled',
    this.faceLivenessPolicy = 'certified',
  });
  final String name;
  final String company;
  final String unit;

  /// Identidade do tablet no servidor (tablet e empresa). Cada registro guardado nasce vinculado a ela.
  final int? deviceId;
  final int? companyId;

  /// 'registration' (só matrícula) ou 'face' (verificação facial ou exceção autorizada).
  final String identificationMode;

  /// 'disabled' ou 'registration_only' (marcação offline por matrícula, sinalizada para revisão).
  final String offlinePolicy;

  /// 'certified' ou 'basic_challenge' (desafio de movimento, não certificado).
  final String faceLivenessPolicy;

  bool get requiresFace => identificationMode == 'face';
  bool get allowsOfflinePunch => offlinePolicy == 'registration_only';

  factory DeviceScope.fromJson(Map<String, dynamic> json) => DeviceScope(
        name: '${json['name']}',
        company: '${(json['company'] as Map<String, dynamic>)['name']}',
        unit: '${(json['unit'] as Map<String, dynamic>)['name']}',
        deviceId: json['device_id'] is int ? json['device_id'] as int : null,
        companyId: (json['company'] as Map<String, dynamic>)['id'] is int
            ? (json['company'] as Map<String, dynamic>)['id'] as int
            : null,
        identificationMode: '${json['identification_mode'] ?? 'registration'}',
        offlinePolicy: '${json['offline_policy'] ?? 'disabled'}',
        faceLivenessPolicy: '${json['face_liveness_policy'] ?? 'certified'}',
      );

  /// Mesmo formato do servidor (usado para guardar o escopo e operar após reinício sem conexão).
  Map<String, dynamic> toJson() => {
        'name': name,
        if (deviceId != null) 'device_id': deviceId,
        'company': {if (companyId != null) 'id': companyId, 'name': company},
        'unit': {'name': unit},
        'identification_mode': identificationMode,
        'offline_policy': offlinePolicy,
        'face_liveness_policy': faceLivenessPolicy,
      };
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

/// Sem conexão: a marcação foi GUARDADA neste tablet e será enviada ao reconectar. Não há NSR nem
/// comprovante até a sincronização; o horário mostrado é o do aparelho.
class PunchQueued extends PunchOutcome {
  const PunchQueued({required this.eventId, required this.deviceTime});
  final String eventId;
  final DateTime deviceTime;
}

/// Resultado da verificação facial 1:1 feita pelo servidor.
/// Desafio de movimento emitido pelo servidor: `steps` são `center`, `left` ou `right`.
class FaceChallenge {
  const FaceChallenge(this.id, this.steps) : fallbackReason = null;

  /// Sem biometria ativa (não consentiu, retirou ou não cadastrou) ou motor fora do ar: a câmera não é
  /// aberta e o ponto é registrado pela matrícula. O servidor confere o motivo de novo na marcação.
  const FaceChallenge.notRequired(this.fallbackReason)
      : id = 0,
        steps = const [];
  final int id;
  final List<String> steps;
  final String? fallbackReason;
  bool get faceRequired => fallbackReason == null;
}

sealed class FaceOutcome {
  const FaceOutcome();
}

class FaceVerified extends FaceOutcome {
  const FaceVerified(this.verificationId, this.verificationToken);
  final int verificationId;
  final String verificationToken;
  Map<String, dynamic> get identification => {
        'method': 'face',
        'verification_id': verificationId,
        'verification_token': verificationToken,
      };
}

/// Não verificado: [outcome] é o código do servidor (no_match, liveness_failed, poor_quality, ...).
class FaceDenied extends FaceOutcome {
  const FaceDenied(this.outcome, this.message);
  final String outcome;
  final String message;
}

class FaceUnavailable extends FaceOutcome {
  const FaceUnavailable(this.message);
  final String message;
}

const _faceMessages = <String, String>{
  'no_match': 'Rosto não reconhecido. Tente novamente ou chame um responsável.',
  'liveness_failed': 'Não foi possível confirmar que é uma pessoa presente. Tente novamente.',
  'poor_quality': 'Imagem com pouca qualidade. Ajuste a posição e a luz e tente novamente.',
  'no_template': 'Sem cadastro facial. Procure o administrador.',
  'no_consent': 'Sem consentimento registrado. Procure o administrador.',
  'locked': 'Verificação facial bloqueada por tentativas. Chame um responsável.',
  'liveness_not_accepted':
      'Rosto reconhecido, mas a prova de presença não atende à política da empresa. Chame um responsável.',
};

String _newEventId() {
  final random = Random.secure();
  final bytes = List<int>.generate(16, (_) => random.nextInt(256));
  bytes[6] = (bytes[6] & 0x0f) | 0x40; // versão 4
  bytes[8] = (bytes[8] & 0x3f) | 0x80; // variante RFC 4122
  final hex = bytes.map((b) => b.toRadixString(16).padLeft(2, '0')).join();
  return '${hex.substring(0, 8)}-${hex.substring(8, 12)}-${hex.substring(12, 16)}-'
      '${hex.substring(16, 20)}-${hex.substring(20)}';
}

/// Ciclo de vida do tablet: ativação, heartbeat, rotação, revogação e sincronização offline.
///
/// Sem conexão, e só se a empresa permitir (`offline_policy`), a marcação por matrícula é guardada na fila
/// persistente e enviada em lote ao reconectar. Reconhecimento facial NÃO funciona offline.
class DeviceController extends ChangeNotifier {
  DeviceController({
    required this.store,
    QueueStorage? queueStorage,
    http.Client? client,
    String? baseUrl,
    DateTime Function()? now,
  })  : queue = OfflineQueue(queueStorage ?? MemoryQueueStorage(), now: now),
        _client = client ?? http.Client(),
        _baseUrl = baseUrl ?? apiBaseUrl,
        _now = now ?? DateTime.now {
    queue.addListener(_onQueueChanged);
  }

  final TokenStore store;
  final OfflineQueue queue;
  final http.Client _client;
  final String _baseUrl;
  final DateTime Function() _now;
  Future<void>? _operation;
  bool _disposed = false;
  bool _syncing = false;

  DeviceState state = DeviceState.loading;
  DeviceScope? scope;
  String? message;

  void _onQueueChanged() {
    if (!_disposed) notifyListeners();
  }

  /// Carrega a fila e o escopo guardado (para operar após reinício mesmo sem conexão) e verifica o acesso.
  Future<void> init() async {
    await queue.load();
    // Tentativas que ficaram sem resposta antes de fechar/reiniciar: reaproveitam o mesmo identificador.
    for (final e in queue.inflight.entries) {
      _pendingPunches.putIfAbsent(e.key, () => e.value);
    }
    final cached = queue.cachedScope;
    if (cached != null && scope == null) {
      try {
        scope = DeviceScope.fromJson(cached);
      } catch (_) {
        scope = null;
      }
    }
    await heartbeat();
  }

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
        // Registros feitos sob OUTRA identidade (outro tablet ou outra empresa) ficam retidos: nunca são
        // enviados automaticamente com a credencial nova, para não caírem em quem tem a mesma matrícula.
        await queue.holdForeign(nextScope.deviceId, nextScope.companyId);
        _pendingPunches.removeWhere((reg, _) => !queue.inflight.containsKey(reg));
        scope = nextScope;
        await queue.saveScope(nextScope.toJson());
        _set(DeviceState.active);
        await syncPending(); // marcações da MESMA identidade seguem para o servidor
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
      final sentAt = _now();
      final response = await _client
          .post(
            Uri.parse('$_baseUrl/api/device/heartbeat/'),
            headers: _headers(credential.token),
            body: jsonEncode({'app_version': appVersion}),
          )
          .timeout(const Duration(seconds: 10));
      final receivedAt = _now();
      if (response.statusCode == 200) {
        final body = jsonDecode(response.body) as Map<String, dynamic>;
        scope = DeviceScope.fromJson(body);
        await queue.saveScope(scope!.toJson());
        await _sampleClock(body['server_time'], sentAt, receivedAt);
        _set(DeviceState.active);
        if (_now().difference(credential.issuedAt) > rotateAfter) await _rotate(credential);
        await syncPending();
        await reconcileInflight();
      } else if (response.statusCode == 401) {
        // Revogado ou expirado: a credencial local não serve mais. A FILA É PRESERVADA.
        scope = null;
        await queue.saveScope(null);
        _set(DeviceState.revoked, _revokedMessage());
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

  String _revokedMessage() {
    final pending = queue.pendingCount;
    final tail = pending > 0
        ? ' $pending marcação(ões) continuam guardadas e serão enviadas após a reativação.'
        : '';
    return 'Este tablet foi desativado. Peça um novo código de ativação.$tail';
  }

  /// Mede o desvio do relógio (servidor − aparelho) pelo ponto médio da requisição.
  Future<void> _sampleClock(dynamic serverTime, DateTime sentAt, DateTime receivedAt) async {
    final server = DateTime.tryParse('$serverTime');
    if (server == null) return;
    final midpoint = sentAt.add(receivedAt.difference(sentAt) ~/ 2);
    final offsetMs = server.toUtc().difference(midpoint.toUtc()).inMilliseconds;
    await queue.saveClock((offsetMs / 1000).round(), server);
  }

  /// Envia a fila offline em lotes. Cada evento recebe resposta própria (confirmed/duplicate/rejected);
  /// o que não receber resposta definitiva volta a `pending`. Credencial revogada/expirada (401), empresa
  /// suspensa (403), 429, 5xx ou falha de rede interrompem o envio SEM perder nada.
  Future<void> syncPending() async {
    if (_syncing || _disposed) return;
    _syncing = true;
    try {
      while (!_disposed) {
        final credential = await store.read();
        if (credential == null) return;
        final batch = await queue.takeBatch(50);
        if (batch.isEmpty) return;
        http.Response response;
        try {
          response = await _client
              .post(
                Uri.parse('$_baseUrl/api/device/punches/batch/'),
                headers: _headers(credential.token),
                body: jsonEncode({'events': batch.map((e) => e.toWire()).toList()}),
              )
              .timeout(const Duration(seconds: 20));
        } catch (_) {
          await queue.releaseSent();
          return;
        }
        if (response.statusCode == 200) {
          try {
            final body = jsonDecode(response.body) as Map<String, dynamic>;
            await queue.applyResults(batch, body['results'] as List<dynamic>);
          } catch (_) {
            await queue.releaseSent(); // resposta ilegível: reenviar é seguro (idempotente)
            return;
          }
          // Sem nenhum resultado definitivo neste lote não há progresso: parar, para não reenviar sem fim.
          if (batch.every((e) => e.state == QueuedState.pending)) return;
          continue;
        }
        await queue.releaseSent();
        if (response.statusCode == 401) {
          scope = null;
          await queue.saveScope(null);
          _set(DeviceState.revoked, _revokedMessage());
          await store.clear();
        } else if (response.statusCode == 403) {
          _set(DeviceState.offline, 'Acesso suspenso. Procure o administrador.');
        }
        return;
      }
    } finally {
      _syncing = false;
      if (!_disposed) notifyListeners();
    }
  }

  Future<void> acknowledgeRejected(String eventId) => queue.acknowledgeRejected(eventId);

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
        await queue.saveScope(null);
        _set(DeviceState.revoked, _revokedMessage());
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
  /// (informativo; a apuração decide). Sem resposta do servidor, e só se a empresa permitir marcação
  /// offline por matrícula, a marcação é guardada na fila persistente ([PunchQueued]).
  Future<PunchOutcome> punch(
    String registration, {
    String declaredKind = '',
    Map<String, dynamic>? identification,
  }) async {
    final reg = registration.trim();
    if (reg.isEmpty) return const PunchRejected('Informe a matrícula.');
    if (_punching) return const PunchUnconfirmed('Aguarde a conclusão do registro anterior.');
    _punching = true;
    final wasUnconfirmed = _pendingPunches.containsKey(reg);
    Map<String, dynamic>? payload;
    try {
      final credential = await store.read();
      if (credential == null) {
        return wasUnconfirmed
            ? const PunchUnconfirmed('Tentativa anterior sem confirmação. Procure o administrador.')
            : const PunchRejected('Tablet não ativado.');
      }
      final isNewAttempt = !_pendingPunches.containsKey(reg);
      payload = _pendingPunches.putIfAbsent(reg, () => {
        'registration': reg,
        'client_event_id': _newEventId(),
        'declared_kind': declaredKind,
        'device_reported_at': _now().toUtc().toIso8601String(),
        if (scope?.deviceId != null) 'origin_device_id': scope!.deviceId,
        if (scope?.companyId != null) 'origin_company_id': scope!.companyId,
        if (identification != null) 'identification': identification,
      });
      // Persiste o identificador ANTES do primeiro envio; se o servidor gravar e a resposta se perder,
      // reiniciar não cria outro evento. (Se o aparelho não conseguir gravar, segue só em memória.)
      if (isNewAttempt) await queue.saveInflight(reg, payload);
      // Renova a identificação (código de exceção ou token facial) sem trocar o evento: se o envio
      // anterior chegou a ser gravado, o servidor devolve a marcação original antes de validar nada.
      if (identification != null) payload['identification'] = identification;
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
        await _closeAttempt(reg);
        return outcome;
      }
      if (response.statusCode == 401) {
        // A recusa atual não prova que uma tentativa anterior não foi gravada.
        if (!wasUnconfirmed) await _closeAttempt(reg);
        scope = null;
        await queue.saveScope(null);
        _set(DeviceState.revoked, _revokedMessage());
        await store.clear();
        if (wasUnconfirmed) {
          return const PunchUnconfirmed('Tablet desativado. Tentativa anterior sem confirmação. Procure o administrador.');
        }
        return const PunchRejected('Tablet desativado. Marcação não registrada.');
      }
      if (response.statusCode == 404 || response.statusCode == 400) {
        // O servidor consulta o evento existente ANTES de validar matrícula ou identificação
        // (contrato coberto por teste no backend). Logo, 400/404 prova que este evento não foi
        // gravado: a tentativa se encerra e a próxima usará um evento novo.
        await _closeAttempt(reg);
        return PunchRejected(response.statusCode == 404
            ? 'Matrícula não encontrada nesta unidade. Marcação não registrada.'
            : 'Dados ou identificação recusados. Marcação não registrada.');
      }
      return const PunchUnconfirmed('Servidor indisponível. Tente novamente: não haverá duplicidade.');
    } catch (_) {
      final pending = payload;
      if (pending != null && _canQueueOffline(pending)) {
        final reported = DateTime.parse(pending['device_reported_at'] as String);
        final queued = await queue.enqueue(
          eventId: pending['client_event_id'] as String,
          registration: reg,
          declaredKind: (pending['declared_kind'] as String?) ?? '',
          deviceReportedAt: reported,
          originDeviceId: scope?.deviceId,
          originCompanyId: scope?.companyId,
        );
        if (queued == null) {
          return const PunchUnconfirmed(
            'Não foi possível guardar a marcação neste tablet (fila cheia ou armazenamento indisponível). Procure o administrador.',
          );
        }
        await _closeAttempt(reg); // a fila assumiu o evento; o reenvio usa o mesmo identificador
        return PunchQueued(eventId: queued.eventId, deviceTime: reported.toLocal());
      }
      return const PunchUnconfirmed('Sem confirmação do servidor. Tente novamente: não haverá duplicidade.');
    } finally {
      _punching = false;
    }
  }

  Future<void> _closeAttempt(String registration) async {
    _pendingPunches.remove(registration);
    await queue.clearInflight(registration);
  }

  /// Resolve tentativas sem resposta deixadas por um fechamento ou reinício. O servidor consulta o evento
  /// pelo identificador ANTES de validar matrícula ou identificação: 200/201 devolve a marcação que ele já
  /// gravou (sem duplicar); 400/404 prova que o evento não existe e a tentativa é descartada. Falha de rede
  /// ou 5xx mantém a tentativa para a próxima vez.
  Future<void> reconcileInflight() async {
    if (_punching || _disposed) return;
    final credential = await store.read();
    if (credential == null) return;
    for (final entry in Map<String, Map<String, dynamic>>.from(_pendingPunches).entries) {
      if (_punching || _disposed) return;
      final persisted = queue.inflight[entry.key];
      if (persisted == null) continue; // só tentativas persistidas (as de memória seguem o fluxo normal)
      try {
        final response = await _client
            .post(
              Uri.parse('$_baseUrl/api/device/punches/'),
              headers: _headers(credential.token),
              body: jsonEncode(persisted),
            )
            .timeout(const Duration(seconds: 10));
        if (response.statusCode == 200 ||
            response.statusCode == 201 ||
            response.statusCode == 400 ||
            response.statusCode == 404) {
          await _closeAttempt(entry.key);
        }
      } catch (_) {
        // Sem resposta: mantém a tentativa.
      }
    }
  }

  /// Offline só por matrícula e só se a empresa permitir. Face e exceção dependem do servidor.
  bool _canQueueOffline(Map<String, dynamic> payload) {
    if (!(scope?.allowsOfflinePunch ?? false)) return false;
    final identification = payload['identification'];
    return identification == null ||
        (identification is Map<String, dynamic> && identification['method'] == 'registration');
  }

  /// Pede ao servidor a sequência imprevisível do desafio de movimento (uso único, prazo curto).
  /// Sem ela não há prova de vivacidade; devolve `null` se não foi possível obter.
  Future<FaceChallenge?> requestChallenge([String registration = '']) async {
    try {
      final credential = await store.read();
      if (credential == null) return null;
      final response = await _client
          .post(
            Uri.parse('$_baseUrl/api/device/face/challenge/'),
            headers: _headers(credential.token),
            body: jsonEncode({if (registration.trim().isNotEmpty) 'registration': registration.trim()}),
          )
          .timeout(const Duration(seconds: 10));
      if (response.statusCode == 200) {
        final body = jsonDecode(response.body) as Map<String, dynamic>;
        if (body['face_required'] == false) return FaceChallenge.notRequired('${body['reason']}');
        return null;
      }
      if (response.statusCode != 201) return null;
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      final id = body['challenge_id'];
      final steps = body['steps'];
      if (id is! int || steps is! List || steps.isEmpty) return null;
      return FaceChallenge(id, [for (final s in steps) '$s']);
    } catch (_) {
      return null;
    }
  }

  /// Envia a captura ao servidor para verificação 1:1. As imagens não são guardadas no aparelho.
  /// [frames]: quadros do desafio de movimento (prova de presença básica).
  Future<FaceOutcome> verifyFace(
    String registration,
    Uint8List image, {
    List<Uint8List> frames = const [],
    int? challengeId,
  }) async {
    final reg = registration.trim();
    if (reg.isEmpty) return const FaceDenied('invalid', 'Informe a matrícula.');
    try {
      final credential = await store.read();
      if (credential == null) return const FaceDenied('invalid', 'Tablet não ativado.');
      final response = await _client
          .post(
            Uri.parse('$_baseUrl/api/device/face/verify/'),
            headers: _headers(credential.token),
            body: jsonEncode({
              'registration': reg,
              'image': base64Encode(image),
              if (frames.isNotEmpty) 'frames': [for (final f in frames) base64Encode(f)],
              if (challengeId != null) 'challenge_id': challengeId,
            }),
          )
          .timeout(const Duration(seconds: 20));
      if (response.statusCode == 404) {
        return const FaceDenied('unknown', 'Matrícula não encontrada nesta unidade.');
      }
      if (response.statusCode == 401) {
        scope = null;
        await queue.saveScope(null);
        _set(DeviceState.revoked, _revokedMessage());
        await store.clear();
        return const FaceUnavailable('Tablet desativado.');
      }
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      final outcome = '${body['outcome']}';
      if (response.statusCode == 200 && outcome == 'success' && body['liveness_accepted'] == false) {
        return FaceDenied('liveness_not_accepted', _faceMessages['liveness_not_accepted']!);
      }
      if (response.statusCode == 200 && outcome == 'success') {
        final id = body['verification_id'];
        final verificationToken = body['verification_token'];
        if (id is int && verificationToken is String && verificationToken.isNotEmpty) {
          return FaceVerified(id, verificationToken);
        }
      }
      if (response.statusCode == 503) return const FaceUnavailable('Verificação facial indisponível.');
      return FaceDenied(outcome, _faceMessages[outcome] ?? 'Verificação não concluída.');
    } catch (_) {
      return const FaceUnavailable('Sem conexão com o servidor para verificar o rosto.');
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
    queue.removeListener(_onQueueChanged);
    queue.dispose();
    _client.close();
    super.dispose();
  }
}
