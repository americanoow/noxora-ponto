import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:noxora_ponto_tablet/device_controller.dart';
import 'package:noxora_ponto_tablet/offline_queue.dart';
import 'package:noxora_ponto_tablet/token_store.dart';

final t0 = DateTime.utc(2026, 10, 24, 12);

Map<String, dynamic> scopeJson({String policy = 'registration_only', DateTime? serverTime, String mode = 'registration'}) => {
      'name': 'Tablet 1',
      'company': {'id': 1, 'name': 'Empresa A'},
      'unit': {'id': 2, 'name': 'Centro'},
      'identification_mode': mode,
      'offline_policy': policy,
      'server_time': (serverTime ?? t0).toUtc().toIso8601String(),
    };

/// Servidor simulado: `online` liga e desliga a rede; `batchHandler` responde ao lote.
class FakeServer {
  bool online = true;
  String policy = 'registration_only';
  Duration serverAhead = const Duration(seconds: 90);
  final batches = <Map<String, dynamic>>[];
  http.Response Function(Map<String, dynamic> body)? batchHandler;
  int batchCalls = 0;

  http.Response confirmAll(Map<String, dynamic> body, {int firstNsr = 1}) {
    var nsr = firstNsr;
    return http.Response(
      jsonEncode({
        'results': [
          for (final e in body['events'] as List<dynamic>)
            {'client_event_id': e['client_event_id'], 'status': 'confirmed', 'record': {'nsr': nsr++}},
        ],
      }),
      200,
    );
  }

  Future<http.Response> handle(http.Request r) async {
    if (!online) throw http.ClientException('sem rede');
    switch (r.url.path) {
      case '/api/device/heartbeat/':
        return http.Response(jsonEncode(scopeJson(policy: policy, serverTime: t0.add(serverAhead))), 200);
      case '/api/device/punches/batch/':
        batchCalls++;
        final body = jsonDecode(r.body) as Map<String, dynamic>;
        batches.add(body);
        return (batchHandler ?? confirmAll)(body);
      case '/api/device/activate/':
        return http.Response(jsonEncode({'token': '9.novo', ...scopeJson(policy: policy)}), 201);
      default:
        return http.Response('{}', 404);
    }
  }
}

DeviceController make(FakeServer server, MemoryTokenStore tokens, MemoryQueueStorage storage) => DeviceController(
      store: tokens,
      queueStorage: storage,
      client: MockClient(server.handle),
      baseUrl: 'http://teste',
      now: () => t0,
    );

MemoryTokenStore credential() => MemoryTokenStore()..value = StoredCredential(token: '7.s', issuedAt: t0);

void main() {
  test('sem rede e com a política ligada, a marcação é guardada e enviada ao reconectar', () async {
    final server = FakeServer();
    final c = make(server, credential(), MemoryQueueStorage());
    await c.init();
    expect(c.state, DeviceState.active);
    expect(c.scope!.allowsOfflinePunch, isTrue);

    server.online = false;
    final outcome = await c.punch('100', declaredKind: 'entry');
    expect(outcome, isA<PunchQueued>());
    expect(c.queue.pendingCount, 1);
    expect(server.batchCalls, 0);

    server.online = true;
    await c.heartbeat();
    expect(server.batchCalls, 1);
    final sent = (server.batches.single['events'] as List).single as Map<String, dynamic>;
    expect(sent['registration'], '100');
    expect(sent['declared_kind'], 'entry');
    expect(sent['client_event_id'], (outcome as PunchQueued).eventId);
    expect(sent['device_reported_at'], t0.toIso8601String()); // horário ORIGINAL do aparelho
    expect(sent['clock_offset_seconds'], 90); // servidor − aparelho na última medição
    expect(sent['offset_measured_at'], t0.add(const Duration(seconds: 90)).toIso8601String());
    expect(c.queue.pendingCount, 0);
    expect(c.queue.items.single.state, QueuedState.confirmed);
    expect(c.queue.items.single.nsr, 1);
    c.dispose();
  });

  test('com a política desligada nada é guardado: fica sem confirmação e o reenvio usa o mesmo evento', () async {
    final server = FakeServer()..policy = 'disabled';
    final c = make(server, credential(), MemoryQueueStorage());
    await c.init();
    server.online = false;
    expect(await c.punch('100'), isA<PunchUnconfirmed>());
    expect(c.queue.items, isEmpty);
    c.dispose();
  });

  test('face e exceção dependem do servidor: não entram na fila offline', () async {
    final server = FakeServer();
    final c = make(server, credential(), MemoryQueueStorage());
    await c.init();
    server.online = false;
    expect(
      await c.punch('100', identification: {'method': 'authorized_exception', 'code': '12345678'}),
      isA<PunchUnconfirmed>(),
    );
    expect(
      await c.punch('200', identification: {'method': 'face', 'verification_id': 1, 'verification_token': 'x'}),
      isA<PunchUnconfirmed>(),
    );
    expect(c.queue.items, isEmpty);
    c.dispose();
  });

  test('a marcação online normal não usa a fila', () async {
    final server = FakeServer();
    final punches = <String>[];
    final c = DeviceController(
      store: credential(),
      queueStorage: MemoryQueueStorage(),
      client: MockClient((r) async {
        if (r.url.path == '/api/device/punches/') {
          punches.add(r.body);
          return http.Response(
            jsonEncode({
              'duplicate': false,
              'record': {'nsr': 4},
              'receipt': {
                'nsr': 4,
                'worker': {'name': 'Maria'},
                'occurred_at': '2026-10-24T09:00:00-03:00',
                'hash_sha256': 'a' * 64,
              },
            }),
            201,
          );
        }
        return server.handle(r);
      }),
      baseUrl: 'http://teste',
      now: () => t0,
    );
    await c.init();
    expect(await c.punch('100'), isA<PunchRecorded>());
    expect(punches.length, 1);
    expect(c.queue.items, isEmpty);
    c.dispose();
  });

  test('recusas 400/404 do servidor NÃO enfileiram: só a falta de resposta enfileira', () async {
    final server = FakeServer();
    final c = DeviceController(
      store: credential(),
      queueStorage: MemoryQueueStorage(),
      client: MockClient((r) async {
        if (r.url.path == '/api/device/punches/') return http.Response('{}', 404);
        return server.handle(r);
      }),
      baseUrl: 'http://teste',
      now: () => t0,
    );
    await c.init();
    expect(await c.punch('999'), isA<PunchRejected>());
    expect(c.queue.items, isEmpty);
    c.dispose();
  });

  test('reinício sem conexão: fila e escopo voltam do armazenamento e o tablet continua marcando', () async {
    final server = FakeServer();
    final tokens = credential();
    final storage = MemoryQueueStorage();
    final first = make(server, tokens, storage);
    await first.init();
    server.online = false;
    await first.punch('100');
    first.dispose();

    final second = make(server, tokens, storage); // app reaberto, ainda sem rede
    await second.init();
    expect(second.state, DeviceState.offline);
    expect(second.scope, isNotNull);
    expect(second.scope!.allowsOfflinePunch, isTrue);
    expect(second.queue.pendingCount, 1);
    expect(await second.punch('200'), isA<PunchQueued>());
    expect(second.queue.pendingCount, 2);
    second.dispose();
  });

  test('lote parcialmente recebido: o evento sem resposta volta e é reenviado depois', () async {
    final server = FakeServer();
    final c = make(server, credential(), MemoryQueueStorage());
    await c.init();
    server.online = false;
    for (final reg in ['1', '2', '3']) {
      await c.punch(reg);
    }
    server.online = true;
    server.batchHandler = (body) {
      final events = (body['events'] as List).where((e) => e['registration'] != '3').toList();
      return server.confirmAll({'events': events});
    };
    await c.heartbeat();
    expect(c.queue.items.where((i) => i.state == QueuedState.confirmed).length, 2);
    expect(c.queue.pendingCount, 1);
    expect(c.queue.items.firstWhere((i) => i.registration == '3').state, QueuedState.pending);

    server.batchHandler = null; // agora o servidor responde por todos
    await c.heartbeat();
    expect(c.queue.pendingCount, 0);
    final lastBatch = server.batches.last['events'] as List;
    expect(lastBatch.map((e) => e['registration']), ['3']); // só o que faltava
    c.dispose();
  });

  test('recusa do servidor fica visível e só some quando uma pessoa reconhece', () async {
    final server = FakeServer();
    final c = make(server, credential(), MemoryQueueStorage());
    await c.init();
    server.online = false;
    await c.punch('999');
    server.online = true;
    server.batchHandler = (body) => http.Response(
          jsonEncode({
            'results': [
              {
                'client_event_id': (body['events'] as List).first['client_event_id'],
                'status': 'rejected',
                'reason': 'unknown_registration',
              }
            ],
          }),
          200,
        );
    await c.heartbeat();
    expect(c.queue.rejectedCount, 1);
    expect(c.queue.pendingCount, 0);
    await c.acknowledgeRejected(c.queue.items.single.eventId);
    expect(c.queue.rejectedCount, 0);
    expect(c.queue.items.length, 1); // continua guardada
    c.dispose();
  });

  test('credencial revogada durante a sincronização preserva a fila e a reativação a envia', () async {
    final server = FakeServer();
    final tokens = credential();
    final c = make(server, tokens, MemoryQueueStorage());
    await c.init();
    server.online = false;
    await c.punch('100');
    await c.punch('200');
    server.online = true;
    server.batchHandler = (_) => http.Response('{}', 401);
    await c.heartbeat();
    expect(c.state, DeviceState.revoked);
    expect(tokens.value, isNull); // credencial apagada
    expect(c.queue.pendingCount, 2); // marcações preservadas
    expect(c.message, contains('continuam guardadas'));
    expect(c.scope, isNull);

    server.batchHandler = null;
    await c.activate('ABCDE-FGHJK'); // novo código do mesmo cadastro
    expect(c.state, DeviceState.active);
    expect(c.queue.pendingCount, 0);
    expect(c.queue.items.where((i) => i.state == QueuedState.confirmed).length, 2);
    expect(server.batches.last['events'].length, 2);
    c.dispose();
  });

  test('empresa suspensa (403), limite (429) e erro de servidor (5xx) interrompem sem perder nada', () async {
    for (final status in [403, 429, 500, 503]) {
      final server = FakeServer();
      final c = make(server, credential(), MemoryQueueStorage());
      await c.init();
      server.online = false;
      await c.punch('100');
      server.online = true;
      server.batchHandler = (_) => http.Response('{}', status);
      await c.heartbeat();
      expect(c.queue.pendingCount, 1, reason: '$status');
      expect(c.queue.items.single.state, QueuedState.pending, reason: '$status');
      expect(server.batchCalls, 1, reason: 'o envio para no primeiro erro ($status)');
      c.dispose();
    }
  });

  test('resposta ilegível ou queda no meio do envio devolve o lote à fila', () async {
    final server = FakeServer();
    final c = make(server, credential(), MemoryQueueStorage());
    await c.init();
    server.online = false;
    await c.punch('100');
    server.online = true;
    server.batchHandler = (_) => http.Response('isto não é json', 200);
    await c.heartbeat();
    expect(c.queue.items.single.state, QueuedState.pending);
    server.batchHandler = (_) => throw http.ClientException('caiu');
    await c.heartbeat();
    expect(c.queue.items.single.state, QueuedState.pending);
    server.batchHandler = null;
    await c.heartbeat();
    expect(c.queue.items.single.state, QueuedState.confirmed);
    c.dispose();
  });

  test('o mesmo evento já gravado pelo servidor volta como duplicado e vira confirmado', () async {
    final server = FakeServer();
    final c = make(server, credential(), MemoryQueueStorage());
    await c.init();
    server.online = false;
    await c.punch('100');
    server.online = true;
    server.batchHandler = (body) => http.Response(
          jsonEncode({
            'results': [
              {
                'client_event_id': (body['events'] as List).first['client_event_id'],
                'status': 'duplicate',
                'record': {'nsr': 5},
              }
            ],
          }),
          200,
        );
    await c.heartbeat();
    expect(c.queue.items.single.state, QueuedState.confirmed);
    expect(c.queue.items.single.nsr, 5);
    c.dispose();
  });

  test('lote sem nenhum resultado definitivo não gera laço infinito de reenvio', () async {
    final server = FakeServer();
    final c = make(server, credential(), MemoryQueueStorage());
    await c.init();
    server.online = false;
    await c.punch('100');
    await c.punch('200');
    server.online = true;
    server.batchHandler = (_) => http.Response(jsonEncode({'results': []}), 200);
    await c.syncPending();
    expect(server.batchCalls, 1); // uma tentativa e para
    expect(c.queue.pendingCount, 2);
    expect(c.queue.items.map((i) => i.state), everyElement(QueuedState.pending));
    c.dispose();
  });

  test('envia em lotes de 50', () async {
    final server = FakeServer();
    final c = make(server, credential(), MemoryQueueStorage());
    await c.init();
    for (var i = 0; i < 120; i++) {
      await c.queue.enqueue(
        eventId: 'ev-$i',
        registration: '100',
        declaredKind: '',
        deviceReportedAt: t0.subtract(Duration(minutes: i)),
      );
    }
    await c.syncPending();
    expect(server.batches.map((b) => (b['events'] as List).length), [50, 50, 20]);
    expect(c.queue.pendingCount, 0);
    c.dispose();
  });

  test('duas sincronizações simultâneas fazem um único envio', () async {
    final server = FakeServer();
    final c = make(server, credential(), MemoryQueueStorage());
    await c.init();
    await c.queue.enqueue(eventId: 'a', registration: '1', declaredKind: '', deviceReportedAt: t0);
    await Future.wait([c.syncPending(), c.syncPending()]);
    expect(server.batchCalls, 1);
    c.dispose();
  });

  test('se o armazenamento falhar, a marcação NÃO é dada como guardada', () async {
    final server = FakeServer();
    final storage = MemoryQueueStorage();
    final c = make(server, credential(), storage);
    await c.init();
    server.online = false;
    storage.failWrites = true;
    final outcome = await c.punch('100');
    expect(outcome, isA<PunchUnconfirmed>());
    expect((outcome as PunchUnconfirmed).message, contains('Não foi possível guardar'));
    expect(c.queue.items, isEmpty);
    c.dispose();
  });

  test('o desvio do relógio é medido pelo ponto médio da requisição e guardado', () async {
    var tick = 0;
    final times = [t0, t0.add(const Duration(seconds: 2))];
    final server = FakeServer()..serverAhead = const Duration(seconds: 61);
    final c = DeviceController(
      store: credential(),
      queueStorage: MemoryQueueStorage(),
      client: MockClient(server.handle),
      baseUrl: 'http://teste',
      now: () => times[tick++ % 2 == 0 ? 0 : 1],
    );
    await c.init();
    // enviado em t0, recebido em t0+2s: ponto médio t0+1s; servidor = t0+61s → desvio de 60 s
    expect(c.queue.clockOffsetSeconds, anyOf(60, 59, 61));
    expect(c.queue.clockMeasuredAt, t0.add(const Duration(seconds: 61)));
    c.dispose();
  });
}
