import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Estados de uma marcação feita sem conexão.
///
/// pending → sent → confirmed (servidor devolveu NSR) | rejected (servidor recusou; exige tratamento humano).
/// `sent` significa "enviado e SEM resposta definitiva": após reinício ou falha volta a pending, e o reenvio é
/// seguro porque o servidor é idempotente pelo identificador do evento. `acknowledged` = recusa vista por
/// uma pessoa (continua guardada por um tempo, mas não conta como pendência).
enum QueuedState { pending, sent, confirmed, rejected, acknowledged }

class QueuedPunch {
  QueuedPunch({
    required this.eventId,
    required this.registration,
    required this.declaredKind,
    required this.deviceReportedAt,
    required this.queuedAt,
    this.clockOffsetSeconds,
    this.offsetMeasuredAt,
    this.state = QueuedState.pending,
    this.attempts = 0,
    this.nsr,
    this.reason,
    this.resolvedAt,
  });

  final String eventId;
  final String registration;
  final String declaredKind;

  /// Horário ORIGINAL do aparelho no instante da marcação (UTC).
  final DateTime deviceReportedAt;
  final DateTime queuedAt;

  /// servidor − aparelho (segundos) na última medição, e o horário do SERVIDOR em que foi medido.
  final int? clockOffsetSeconds;
  final DateTime? offsetMeasuredAt;

  QueuedState state;
  int attempts;
  int? nsr;
  String? reason;
  DateTime? resolvedAt;

  Map<String, dynamic> toWire() => {
        'client_event_id': eventId,
        'registration': registration,
        'declared_kind': declaredKind,
        'device_reported_at': deviceReportedAt.toUtc().toIso8601String(),
        'clock_offset_seconds': clockOffsetSeconds,
        'offset_measured_at': offsetMeasuredAt?.toUtc().toIso8601String(),
      };

  Map<String, dynamic> toJson() => {
        'id': eventId,
        'reg': registration,
        'kind': declaredKind,
        'reported': deviceReportedAt.toUtc().toIso8601String(),
        'queued': queuedAt.toUtc().toIso8601String(),
        'offset': clockOffsetSeconds,
        'measured': offsetMeasuredAt?.toUtc().toIso8601String(),
        'state': state.name,
        'attempts': attempts,
        'nsr': nsr,
        'reason': reason,
        'resolved': resolvedAt?.toUtc().toIso8601String(),
      };

  factory QueuedPunch.fromJson(Map<String, dynamic> json) => QueuedPunch(
        eventId: json['id'] as String,
        registration: json['reg'] as String,
        declaredKind: (json['kind'] as String?) ?? '',
        deviceReportedAt: DateTime.parse(json['reported'] as String).toUtc(),
        queuedAt: DateTime.parse(json['queued'] as String).toUtc(),
        clockOffsetSeconds: json['offset'] as int?,
        offsetMeasuredAt: json['measured'] == null ? null : DateTime.parse(json['measured'] as String).toUtc(),
        state: QueuedState.values.byName(json['state'] as String),
        attempts: (json['attempts'] as int?) ?? 0,
        nsr: json['nsr'] as int?,
        reason: json['reason'] as String?,
        resolvedAt: json['resolved'] == null ? null : DateTime.parse(json['resolved'] as String).toUtc(),
      );
}

/// Persistência bruta da fila (uma string JSON). Implementações: armazenamento seguro do Android e memória.
abstract class QueueStorage {
  Future<String?> read();
  Future<void> write(String value);

  /// Guarda o conteúdo ilegível sem apagá-lo, para análise posterior.
  Future<void> quarantine(String raw);
}

/// Armazenamento protegido no Android (Keystore, via EncryptedSharedPreferences).
///
/// Proteção em repouso NÃO é garantia de integridade contra um aparelho com acesso root: os controles
/// compensatórios estão no servidor (sinalizações de revisão, limite de idade, idempotência).
class SecureQueueStorage implements QueueStorage {
  SecureQueueStorage([FlutterSecureStorage? storage])
      : _storage = storage ??
            const FlutterSecureStorage(aOptions: AndroidOptions(encryptedSharedPreferences: true));

  final FlutterSecureStorage _storage;
  static const _key = 'offline_punch_queue_v1';
  static const _corruptKey = 'offline_punch_queue_v1_corrupt';

  @override
  Future<String?> read() => _storage.read(key: _key);

  @override
  Future<void> write(String value) => _storage.write(key: _key, value: value);

  @override
  Future<void> quarantine(String raw) => _storage.write(key: _corruptKey, value: raw);
}

/// Somente para testes.
class MemoryQueueStorage implements QueueStorage {
  String? value;
  String? quarantined;
  bool failWrites = false;

  @override
  Future<String?> read() async => value;

  @override
  Future<void> write(String next) async {
    if (failWrites) throw StateError('falha de gravação simulada');
    value = next;
  }

  @override
  Future<void> quarantine(String raw) async => quarantined = raw;
}

/// Fila persistente de marcações offline.
///
/// Toda alteração é gravada ANTES de a operação ser considerada concluída; mutações são serializadas.
class OfflineQueue extends ChangeNotifier {
  OfflineQueue(this.storage, {DateTime Function()? now, this.maxItems = 2000})
      : _now = now ?? DateTime.now;

  final QueueStorage storage;
  final DateTime Function() _now;
  final int maxItems;

  static const int keepConfirmed = 50;
  static const Duration keepConfirmedFor = Duration(hours: 24);
  static const Duration keepAcknowledgedFor = Duration(days: 30);

  final List<QueuedPunch> _items = [];
  Map<String, dynamic>? _scope;
  int? _clockOffsetSeconds;
  DateTime? _clockMeasuredAt;
  bool _corrupt = false;
  Future<void> _serial = Future<void>.value();

  List<QueuedPunch> get items => List.unmodifiable(_items);

  /// Pendência = ainda não confirmada pelo servidor (pending ou sent).
  int get pendingCount =>
      _items.where((i) => i.state == QueuedState.pending || i.state == QueuedState.sent).length;
  int get rejectedCount => _items.where((i) => i.state == QueuedState.rejected).length;
  int get confirmedCount => _items.where((i) => i.state == QueuedState.confirmed).length;

  /// O conteúdo salvo estava ilegível e foi posto em quarentena (nada foi apagado).
  bool get corrupt => _corrupt;
  Map<String, dynamic>? get cachedScope => _scope;
  int? get clockOffsetSeconds => _clockOffsetSeconds;
  DateTime? get clockMeasuredAt => _clockMeasuredAt;

  Future<T> _locked<T>(Future<T> Function() action) {
    final result = _serial.then((_) => action());
    _serial = result.then<void>((_) {}, onError: (_) {});
    return result;
  }

  /// Carrega o estado salvo. `sent` volta a `pending` (recuperação após fechamento ou reinício).
  Future<void> load() => _locked(() async {
        final raw = await storage.read();
        _items.clear();
        _scope = null;
        _clockOffsetSeconds = null;
        _clockMeasuredAt = null;
        _corrupt = false;
        if (raw == null || raw.isEmpty) {
          notifyListeners();
          return;
        }
        try {
          final data = jsonDecode(raw) as Map<String, dynamic>;
          for (final item in (data['items'] as List<dynamic>)) {
            _items.add(QueuedPunch.fromJson(item as Map<String, dynamic>));
          }
          _scope = data['scope'] as Map<String, dynamic>?;
          final clock = data['clock'] as Map<String, dynamic>?;
          if (clock != null) {
            _clockOffsetSeconds = clock['offset'] as int?;
            _clockMeasuredAt = DateTime.parse(clock['measured_at'] as String).toUtc();
          }
        } catch (_) {
          _items.clear();
          _scope = null;
          _clockOffsetSeconds = null;
          _clockMeasuredAt = null;
          _corrupt = true;
          await storage.quarantine(raw); // preserva o conteúdo ilegível
        }
        var recovered = false;
        for (final item in _items) {
          if (item.state == QueuedState.sent) {
            item.state = QueuedState.pending;
            recovered = true;
          }
        }
        if (recovered) await _persist();
        notifyListeners();
      });

  Future<void> _persist() => storage.write(jsonEncode({
        'v': 1,
        'items': _items.map((i) => i.toJson()).toList(),
        'scope': _scope,
        'clock': _clockOffsetSeconds == null || _clockMeasuredAt == null
            ? null
            : {'offset': _clockOffsetSeconds, 'measured_at': _clockMeasuredAt!.toUtc().toIso8601String()},
      }));

  /// Enfileira uma marcação. Devolve null se a fila estiver cheia ou se a gravação falhar:
  /// nesse caso a marcação NÃO foi guardada e quem chamou precisa avisar a pessoa.
  Future<QueuedPunch?> enqueue({
    required String eventId,
    required String registration,
    required String declaredKind,
    required DateTime deviceReportedAt,
  }) =>
      _locked(() async {
        if (_items.any((i) => i.eventId == eventId)) {
          return _items.firstWhere((i) => i.eventId == eventId);
        }
        _prune();
        if (_items.length >= maxItems) return null;
        final item = QueuedPunch(
          eventId: eventId,
          registration: registration,
          declaredKind: declaredKind,
          deviceReportedAt: deviceReportedAt.toUtc(),
          queuedAt: _now().toUtc(),
          clockOffsetSeconds: _clockOffsetSeconds,
          offsetMeasuredAt: _clockMeasuredAt,
        );
        _items.add(item);
        try {
          await _persist();
        } catch (_) {
          _items.remove(item);
          return null;
        }
        notifyListeners();
        return item;
      });

  /// Seleciona até [max] pendentes (na ordem da fila) e os marca como `sent`, já persistido.
  Future<List<QueuedPunch>> takeBatch(int max) => _locked(() async {
        final batch = _items.where((i) => i.state == QueuedState.pending).take(max).toList();
        if (batch.isEmpty) return <QueuedPunch>[];
        for (final item in batch) {
          item.state = QueuedState.sent;
          item.attempts += 1;
        }
        try {
          await _persist();
        } catch (_) {
          for (final item in batch) {
            item.state = QueuedState.pending;
            item.attempts -= 1;
          }
          return <QueuedPunch>[];
        }
        notifyListeners();
        return batch;
      });

  /// Aplica a resposta de um lote. Por evento: confirmed/duplicate → confirmed (NSR); rejected → rejected;
  /// evento ausente da resposta (lote parcialmente recebido) → volta a pending.
  Future<void> applyResults(List<QueuedPunch> sent, List<dynamic> results) => _locked(() async {
        final byId = <String, Map<String, dynamic>>{};
        for (final r in results) {
          if (r is Map<String, dynamic> && r['client_event_id'] is String) {
            byId[r['client_event_id'] as String] = r;
          }
        }
        final now = _now().toUtc();
        for (final item in sent) {
          final result = byId[item.eventId];
          final status = result?['status'];
          if (status == 'confirmed' || status == 'duplicate') {
            item.state = QueuedState.confirmed;
            final record = result!['record'];
            item.nsr = record is Map<String, dynamic> && record['nsr'] is num ? (record['nsr'] as num).toInt() : null;
            item.resolvedAt = now;
          } else if (status == 'rejected') {
            item.state = QueuedState.rejected;
            item.reason = '${result!['reason'] ?? 'unknown'}';
            item.resolvedAt = now;
          } else {
            item.state = QueuedState.pending; // sem resposta definitiva para este evento
          }
        }
        _prune();
        await _persist();
        notifyListeners();
      });

  /// Falha de comunicação: tudo que estava `sent` volta a `pending` (nada se perde).
  Future<void> releaseSent() => _locked(() async {
        var changed = false;
        for (final item in _items) {
          if (item.state == QueuedState.sent) {
            item.state = QueuedState.pending;
            changed = true;
          }
        }
        if (changed) await _persist();
        notifyListeners();
      });

  /// Uma pessoa viu a recusa. O registro continua guardado (para consulta), mas deixa de contar como pendência.
  Future<void> acknowledgeRejected(String eventId) => _locked(() async {
        for (final item in _items) {
          if (item.eventId == eventId && item.state == QueuedState.rejected) {
            item.state = QueuedState.acknowledged;
            item.resolvedAt = _now().toUtc();
          }
        }
        await _persist();
        notifyListeners();
      });

  Future<void> saveScope(Map<String, dynamic>? scope) => _locked(() async {
        _scope = scope;
        try {
          await _persist();
        } catch (_) {
          // Falha ao guardar o escopo não pode derrubar a operação; ele é regravado no próximo heartbeat.
        }
      });

  Future<void> saveClock(int offsetSeconds, DateTime measuredAtServerTime) => _locked(() async {
        _clockOffsetSeconds = offsetSeconds;
        _clockMeasuredAt = measuredAtServerTime.toUtc();
        try {
          await _persist();
        } catch (_) {
          // idem: é só uma amostra, remedida no próximo heartbeat.
        }
      });

  void _prune() {
    final now = _now().toUtc();
    final confirmed = _items.where((i) => i.state == QueuedState.confirmed).toList()
      ..sort((a, b) => (b.resolvedAt ?? now).compareTo(a.resolvedAt ?? now));
    for (var i = 0; i < confirmed.length; i++) {
      final age = now.difference(confirmed[i].resolvedAt ?? now);
      if (i >= keepConfirmed || age > keepConfirmedFor) _items.remove(confirmed[i]);
    }
    _items.removeWhere((i) =>
        i.state == QueuedState.acknowledged &&
        now.difference(i.resolvedAt ?? now) > keepAcknowledgedFor);
  }
}
