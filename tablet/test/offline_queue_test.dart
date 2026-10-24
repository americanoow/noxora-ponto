import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:noxora_ponto_tablet/offline_queue.dart';

final t0 = DateTime.utc(2026, 10, 24, 12);

OfflineQueue build(MemoryQueueStorage storage, {int maxItems = 2000, DateTime Function()? now}) =>
    OfflineQueue(storage, maxItems: maxItems, now: now ?? () => t0);

Future<QueuedPunch?> add(OfflineQueue q, String id, {String reg = '100'}) => q.enqueue(
      eventId: id,
      registration: reg,
      declaredKind: 'entry',
      deviceReportedAt: t0.subtract(const Duration(minutes: 5)),
    );

Map<String, dynamic> result(String id, String status, {int? nsr, String? reason}) => {
      'client_event_id': id,
      'status': status,
      if (nsr != null) 'record': {'nsr': nsr},
      if (reason != null) 'reason': reason,
    };

void main() {
  test('enfileirar persiste e sobrevive ao reinício (nova instância, mesmo armazenamento)', () async {
    final storage = MemoryQueueStorage();
    final q = build(storage);
    await q.load();
    expect(await add(q, 'e1'), isNotNull);
    expect(await add(q, 'e2'), isNotNull);
    expect(q.pendingCount, 2);

    final restarted = build(storage);
    await restarted.load();
    expect(restarted.items.map((i) => i.eventId), ['e1', 'e2']);
    expect(restarted.items.first.registration, '100');
    expect(restarted.items.first.deviceReportedAt, t0.subtract(const Duration(minutes: 5)));
    expect(restarted.pendingCount, 2);
  });

  test('o mesmo evento enfileirado duas vezes não duplica', () async {
    final q = build(MemoryQueueStorage());
    await q.load();
    final a = await add(q, 'e1');
    final b = await add(q, 'e1');
    expect(identical(a, b), isTrue);
    expect(q.items.length, 1);
  });

  test('eventos enviados sem resposta voltam a pendentes após reinício', () async {
    final storage = MemoryQueueStorage();
    final q = build(storage);
    await q.load();
    await add(q, 'e1');
    await add(q, 'e2');
    final batch = await q.takeBatch(50);
    expect(batch.map((i) => i.state), everyElement(QueuedState.sent));
    expect(batch.first.attempts, 1);

    final restarted = build(storage); // o app fechou com o lote em voo
    await restarted.load();
    expect(restarted.items.map((i) => i.state), everyElement(QueuedState.pending));
    expect(restarted.pendingCount, 2);
  });

  test('takeBatch respeita o limite e a ordem da fila', () async {
    final q = build(MemoryQueueStorage());
    await q.load();
    for (var i = 0; i < 5; i++) {
      await add(q, 'e$i');
    }
    final first = await q.takeBatch(2);
    expect(first.map((i) => i.eventId), ['e0', 'e1']);
    final second = await q.takeBatch(10);
    expect(second.map((i) => i.eventId), ['e2', 'e3', 'e4']);
    expect(await q.takeBatch(10), isEmpty);
  });

  test('resultado parcial: confirmado, duplicado, recusado e ausente tratados por evento', () async {
    final q = build(MemoryQueueStorage());
    await q.load();
    for (final id in ['ok', 'dup', 'bad', 'sem-resposta']) {
      await add(q, id);
    }
    final batch = await q.takeBatch(50);
    await q.applyResults(batch, [
      result('ok', 'confirmed', nsr: 7),
      result('dup', 'duplicate', nsr: 3),
      result('bad', 'rejected', reason: 'unknown_registration'),
    ]);
    QueuedPunch by(String id) => q.items.firstWhere((i) => i.eventId == id);
    expect(by('ok').state, QueuedState.confirmed);
    expect(by('ok').nsr, 7);
    expect(by('dup').state, QueuedState.confirmed);
    expect(by('bad').state, QueuedState.rejected);
    expect(by('bad').reason, 'unknown_registration');
    expect(by('sem-resposta').state, QueuedState.pending); // lote parcialmente recebido
    expect(q.pendingCount, 1);
    expect(q.rejectedCount, 1);
  });

  test('resposta com itens malformados não perde eventos', () async {
    final q = build(MemoryQueueStorage());
    await q.load();
    await add(q, 'e1');
    final batch = await q.takeBatch(50);
    await q.applyResults(batch, ['texto', 42, null, {'status': 'confirmed'}, {'client_event_id': 7}]);
    expect(q.items.single.state, QueuedState.pending);
  });

  test('releaseSent devolve tudo a pendente (falha de comunicação)', () async {
    final q = build(MemoryQueueStorage());
    await q.load();
    await add(q, 'e1');
    await q.takeBatch(50);
    await q.releaseSent();
    expect(q.items.single.state, QueuedState.pending);
  });

  test('conteúdo corrompido vai para quarentena e nunca é descartado', () async {
    final storage = MemoryQueueStorage()..value = '{"items": [ não é json';
    final q = build(storage);
    await q.load();
    expect(q.corrupt, isTrue);
    expect(q.items, isEmpty);
    expect(storage.quarantined, '{"items": [ não é json');
    // continua utilizável
    expect(await add(q, 'novo'), isNotNull);
  });

  test('fila cheia recusa e informa (a marcação NÃO foi guardada)', () async {
    final q = build(MemoryQueueStorage(), maxItems: 2);
    await q.load();
    expect(await add(q, 'a'), isNotNull);
    expect(await add(q, 'b'), isNotNull);
    expect(await add(q, 'c'), isNull);
    expect(q.items.length, 2);
  });

  test('falha ao gravar no armazenamento: enqueue devolve null e não deixa o item em memória', () async {
    final storage = MemoryQueueStorage();
    final q = build(storage);
    await q.load();
    storage.failWrites = true;
    expect(await add(q, 'a'), isNull);
    expect(q.items, isEmpty);
    storage.failWrites = false;
    expect(await add(q, 'a'), isNotNull);
  });

  test('recusa reconhecida deixa de contar, mas continua guardada', () async {
    final q = build(MemoryQueueStorage());
    await q.load();
    await add(q, 'bad');
    await q.applyResults(await q.takeBatch(50), [result('bad', 'rejected', reason: 'too_old')]);
    expect(q.rejectedCount, 1);
    await q.acknowledgeRejected('bad');
    expect(q.rejectedCount, 0);
    expect(q.items.single.state, QueuedState.acknowledged);
  });

  test('poda confirmadas antigas ou em excesso, sem tocar em pendentes', () async {
    var now = t0;
    final q = build(MemoryQueueStorage(), now: () => now);
    await q.load();
    for (var i = 0; i < 60; i++) {
      await add(q, 'c$i');
    }
    await q.applyResults(
      await q.takeBatch(100),
      [for (var i = 0; i < 60; i++) result('c$i', 'confirmed', nsr: i + 1)],
    );
    await add(q, 'pendente');
    expect(q.confirmedCount, lessThanOrEqualTo(OfflineQueue.keepConfirmed));
    expect(q.items.any((i) => i.eventId == 'pendente' && i.state == QueuedState.pending), isTrue);
    now = t0.add(const Duration(days: 2));
    await add(q, 'depois');
    expect(q.confirmedCount, 0); // passaram de 24 h
    expect(q.pendingCount, 2);
  });

  test('escopo e amostra de relógio são persistidos; o evento carrega a última medição', () async {
    final storage = MemoryQueueStorage();
    final q = build(storage);
    await q.load();
    await q.saveScope({'name': 'T', 'company': {'name': 'E'}, 'unit': {'name': 'U'}, 'offline_policy': 'registration_only'});
    await q.saveClock(-12, t0);
    final item = (await add(q, 'e1'))!;
    expect(item.clockOffsetSeconds, -12);
    expect(item.offsetMeasuredAt, t0);

    final restarted = build(storage);
    await restarted.load();
    expect(restarted.cachedScope!['offline_policy'], 'registration_only');
    expect(restarted.clockOffsetSeconds, -12);
    expect(restarted.clockMeasuredAt, t0);
    await restarted.saveScope(null);
    final again = build(storage);
    await again.load();
    expect(again.cachedScope, isNull);
  });

  test('formato enviado ao servidor', () async {
    final q = build(MemoryQueueStorage());
    await q.load();
    await q.saveClock(30, t0);
    final item = (await add(q, 'e1', reg: '555'))!;
    expect(item.toWire(), {
      'client_event_id': 'e1',
      'registration': '555',
      'declared_kind': 'entry',
      'device_reported_at': t0.subtract(const Duration(minutes: 5)).toIso8601String(),
      'clock_offset_seconds': 30,
      'offset_measured_at': t0.toIso8601String(),
    });
    expect(jsonDecode(jsonEncode(item.toJson()))['state'], 'pending');
  });
}
