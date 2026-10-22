import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:noxora_ponto_tablet/device_controller.dart';
import 'package:noxora_ponto_tablet/token_store.dart';

const scopeBody = {
  'name': 'Tablet 1',
  'company': {'id': 1, 'name': 'Empresa A'},
  'unit': {'id': 2, 'name': 'Centro'},
};

DeviceController build(MemoryTokenStore store, MockClientHandler handler, {DateTime Function()? now}) =>
    DeviceController(store: store, client: MockClient(handler), baseUrl: 'http://teste', now: now);

class UnreadableStore extends MemoryTokenStore {
  @override
  Future<StoredCredential?> read() async => throw StateError('Keystore indisponível');
}

class UndeletableStore extends MemoryTokenStore {
  @override
  Future<void> clear() async => throw StateError('Keystore indisponível');
}

void main() {
  punchTests();
  faceTests();
  test('falha ao apagar token após revogação na rotação não mantém tablet ativo', () async {
    final store = UndeletableStore()
      ..value = StoredCredential(token: '7.velho', issuedAt: DateTime.utc(2020));
    final c = build(store, (r) async => r.url.path.endsWith('rotate-credential/')
        ? http.Response('{}', 401) : http.Response(jsonEncode(scopeBody), 200));
    await c.init();
    expect(c.state, DeviceState.revoked);
    expect(c.scope, isNull);
    c.dispose();
  });
  test('erro no armazenamento não equivale a tablet sem credencial', () async {
    final c = build(UnreadableStore(), (_) async => throw StateError('Não deve chamar a rede'));
    await c.init();
    expect(c.state, DeviceState.offline);
    expect(c.message, contains('credencial segura'));
    c.dispose();
  });
  test('heartbeats simultâneos compartilham uma operação e uma rotação', () async {
    final now = DateTime.utc(2026, 10, 21);
    final store = MemoryTokenStore()
      ..value = StoredCredential(token: '7.velho', issuedAt: now.subtract(const Duration(days: 25)));
    final response = Completer<http.Response>();
    var heartbeats = 0;
    var rotations = 0;
    final c = build(store, (r) async {
      if (r.url.path.endsWith('rotate-credential/')) {
        rotations++;
        return http.Response('{"token":"8.novo"}', 200);
      }
      heartbeats++;
      return response.future;
    }, now: () => now);
    final first = c.heartbeat();
    final second = c.heartbeat();
    response.complete(http.Response(jsonEncode(scopeBody), 200));
    await Future.wait([first, second]);
    expect(heartbeats, 1);
    expect(rotations, 1);
    expect((await store.read())?.token, '8.novo');
    c.dispose();
  });

  test('401 na rotação retira o estado ativo e limpa credencial', () async {
    final store = MemoryTokenStore()
      ..value = StoredCredential(token: '7.velho', issuedAt: DateTime.utc(2020));
    final c = build(store, (r) async => r.url.path.endsWith('rotate-credential/')
        ? http.Response('{}', 401) : http.Response(jsonEncode(scopeBody), 200));
    await c.init();
    expect(c.state, DeviceState.revoked);
    expect(await store.read(), isNull);
    c.dispose();
  });

  test('resposta tardia após dispose não notifica listeners', () async {
    final store = MemoryTokenStore()
      ..value = StoredCredential(token: '7.s', issuedAt: DateTime.now());
    final response = Completer<http.Response>();
    final started = Completer<void>();
    final c = build(store, (_) {
      started.complete();
      return response.future;
    });
    final pending = c.heartbeat();
    await started.future;
    c.dispose();
    response.complete(http.Response(jsonEncode(scopeBody), 200));
    await pending;
  });

  test('sem credencial fica aguardando ativação', () async {
    final c = build(MemoryTokenStore(), (_) async => http.Response('{}', 200));
    await c.init();
    expect(c.state, DeviceState.unactivated);
  });

  test('ativação grava a credencial e passa a ativo', () async {
    final store = MemoryTokenStore();
    final c = build(store, (r) async {
      expect(r.url.path, '/api/device/activate/');
      expect(jsonDecode(r.body)['code'], 'ABCDE-FGHJK');
      return http.Response(jsonEncode({'token': '7.segredo', ...scopeBody}), 201);
    });
    await c.activate('ABCDE-FGHJK');
    expect(c.state, DeviceState.active);
    expect(c.scope?.unit, 'Centro');
    expect((await store.read())?.token, '7.segredo');
  });

  test('código inválido mantém o tablet sem credencial', () async {
    final store = MemoryTokenStore();
    final c = build(store, (_) async => http.Response('{"detail":"x"}', 400));
    await c.activate('ERRADO');
    expect(c.state, DeviceState.unactivated);
    expect(c.message, 'Código inválido ou expirado.');
    expect(await store.read(), isNull);
  });

  test('revogação (401) apaga a credencial local', () async {
    final store = MemoryTokenStore()..value = StoredCredential(token: '7.s', issuedAt: DateTime.now());
    final c = build(store, (_) async => http.Response('{}', 401));
    await c.init();
    expect(c.state, DeviceState.revoked);
    expect(await store.read(), isNull);
  });

  test('empresa suspensa (403) mantém a credencial', () async {
    final store = MemoryTokenStore()..value = StoredCredential(token: '7.s', issuedAt: DateTime.now());
    final c = build(store, (_) async => http.Response('{}', 403));
    await c.init();
    expect(c.state, DeviceState.offline);
    expect(await store.read(), isNotNull);
  });

  test('falha de rede mantém a credencial e fica offline', () async {
    final store = MemoryTokenStore()..value = StoredCredential(token: '7.s', issuedAt: DateTime.now());
    final c = build(store, (_) async => throw http.ClientException('sem rede'));
    await c.init();
    expect(c.state, DeviceState.offline);
    expect(await store.read(), isNotNull);
  });

  test('credencial antiga é rotacionada após o heartbeat', () async {
    final now = DateTime.utc(2026, 10, 21);
    final store = MemoryTokenStore()
      ..value = StoredCredential(token: '7.velho', issuedAt: now.subtract(const Duration(days: 25)));
    final c = build(store, (r) async {
      if (r.url.path.endsWith('rotate-credential/')) {
        expect(r.headers['Authorization'], 'Device 7.velho');
        return http.Response('{"token":"8.novo"}', 200);
      }
      return http.Response(jsonEncode(scopeBody), 200);
    }, now: () => now);
    await c.init();
    expect(c.state, DeviceState.active);
    expect((await store.read())?.token, '8.novo');
  });
}

// ---------- Marcação de ponto ----------

const punchOk = {
  'duplicate': false,
  'record': {'nsr': 3},
  'receipt': {
    'nsr': 3,
    'worker': {'name': 'Maria'},
    'occurred_at': '2026-10-21T23:30:15-03:00',
    'hash_sha256': 'abcdef0123456789abcdef',
  },
};

DeviceController activeController(MockClientHandler handler, {MemoryTokenStore? store}) => build(
      store ?? (MemoryTokenStore()..value = StoredCredential(token: '7.s', issuedAt: DateTime.now())),
      handler,
    );

void punchTests() {
  test('alternar matrícula preserva o evento e payload anterior', () async {
    final sent = <Map<String, dynamic>>[];
    final c = activeController((r) async {
      sent.add(jsonDecode(r.body) as Map<String, dynamic>);
      if (sent.length == 1) throw http.ClientException('rede');
      return http.Response(jsonEncode(punchOk), 200);
    });
    await c.punch('100', declaredKind: 'entry');
    await c.punch('200');
    expect(await c.punch('100', declaredKind: 'exit'), isA<PunchRecorded>());
    expect(sent[2], sent[0]);
    expect(sent[1]['client_event_id'], isNot(sent[0]['client_event_id']));
    c.dispose();
  });

  test('resposta incompleta não descarta o evento pendente', () async {
    final ids = <String>[];
    final c = activeController((r) async {
      ids.add((jsonDecode(r.body) as Map<String, dynamic>)['client_event_id'] as String);
      if (ids.length == 1) return http.Response('{"receipt":{}}', 201);
      return http.Response(jsonEncode(punchOk), 200);
    });
    expect(await c.punch('100'), isA<PunchUnconfirmed>());
    expect(await c.punch('100'), isA<PunchRecorded>());
    expect(ids[0], ids[1]);
    c.dispose();
  });

  for (final status in [400, 401, 404]) {
    test('recusa $status após falha não afirma ausência do registro anterior', () async {
      var count = 0;
      final c = activeController((r) async {
        if (++count == 1) throw http.ClientException('rede');
        return http.Response('{}', status);
      });
      expect(await c.punch('100'), isA<PunchUnconfirmed>());
      expect(await c.punch('100'), isA<PunchUnconfirmed>());
      c.dispose();
    });
  }

  test('marcação enviada com credencial, identificador de evento UUID e retorna o NSR', () async {
    late Map<String, dynamic> sent;
    late Map<String, String> headers;
    final c = activeController((r) async {
      sent = jsonDecode(r.body) as Map<String, dynamic>;
      headers = r.headers;
      return http.Response(jsonEncode(punchOk), 201);
    });
    final outcome = await c.punch(' 100 ', declaredKind: 'entry');
    expect(outcome, isA<PunchRecorded>());
    expect((outcome as PunchRecorded).nsr, 3);
    expect(outcome.duplicate, isFalse);
    expect(sent['registration'], '100');
    expect(sent['declared_kind'], 'entry');
    expect(sent['client_event_id'], matches(RegExp(r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')));
    expect(headers['Authorization'], 'Device 7.s');
    c.dispose();
  });

  test('sem resposta, o reenvio reutiliza o mesmo evento; após sucesso, um novo evento', () async {
    final ids = <String>[];
    var attempt = 0;
    final c = activeController((r) async {
      ids.add((jsonDecode(r.body) as Map<String, dynamic>)['client_event_id'] as String);
      attempt++;
      if (attempt == 1) throw http.ClientException('rede');
      return http.Response(jsonEncode(punchOk), 200);
    });
    expect(await c.punch('100'), isA<PunchUnconfirmed>());
    expect(await c.punch('100'), isA<PunchRecorded>());
    expect(ids[0], ids[1]);
    await c.punch('100');
    expect(ids[2], isNot(ids[0]));
    c.dispose();
  });

  test('matrícula diferente após falha de rede gera novo evento', () async {
    final ids = <String>[];
    var attempt = 0;
    final c = activeController((r) async {
      ids.add((jsonDecode(r.body) as Map<String, dynamic>)['client_event_id'] as String);
      if (++attempt == 1) throw http.ClientException('rede');
      return http.Response(jsonEncode(punchOk), 201);
    });
    await c.punch('100');
    await c.punch('200');
    expect(ids[0], isNot(ids[1]));
    c.dispose();
  });

  test('matrícula não encontrada encerra a tentativa sem gravar', () async {
    final c = activeController((_) async => http.Response('{}', 404));
    expect(await c.punch('999'), isA<PunchRejected>());
    c.dispose();
  });

  test('credencial revogada durante a marcação desativa o tablet e informa que nada foi gravado', () async {
    final store = MemoryTokenStore()..value = StoredCredential(token: '7.s', issuedAt: DateTime.now());
    final c = activeController((_) async => http.Response('{}', 401), store: store);
    final outcome = await c.punch('100');
    expect(outcome, isA<PunchRejected>());
    expect((outcome as PunchRejected).message, contains('não registrada'));
    expect(c.state, DeviceState.revoked);
    expect(await store.read(), isNull);
    c.dispose();
  });

  test('matrícula vazia não chama a rede', () async {
    final c = activeController((_) async => throw StateError('não deve chamar a rede'));
    expect(await c.punch('   '), isA<PunchRejected>());
    c.dispose();
  });
}

// ---------- Verificação facial e exceção ----------

void faceTests() {
  test('verificação facial bem-sucedida devolve o id e envia a imagem em base64 com credencial', () async {
    late Map<String, dynamic> sent;
    late Map<String, String> headers;
    final c = activeController((r) async {
      sent = jsonDecode(r.body) as Map<String, dynamic>;
      headers = r.headers;
      return http.Response(
        jsonEncode({'outcome': 'success', 'liveness': 'passed', 'verification_id': 12, 'verification_token': 'signed-token'}),
        200,
      );
    });
    final result = await c.verifyFace(' 100 ', Uint8List.fromList([1, 2, 3]));
    expect(result, isA<FaceVerified>());
    expect((result as FaceVerified).verificationId, 12);
    expect(result.verificationToken, 'signed-token');
    expect(result.identification['verification_token'], 'signed-token');
    expect(sent['registration'], '100');
    expect(base64Decode(sent['image'] as String), [1, 2, 3]);
    expect(headers['Authorization'], 'Device 7.s');
    c.dispose();
  });

  test('falhas de verificação trazem mensagem clara e não liberam a marcação', () async {
    for (final outcome in ['no_match', 'liveness_failed', 'poor_quality', 'no_template', 'locked']) {
      final c = activeController((_) async => http.Response(jsonEncode({'outcome': outcome}), 200));
      final result = await c.verifyFace('100', Uint8List.fromList([1]));
      expect(result, isA<FaceDenied>(), reason: outcome);
      expect((result as FaceDenied).outcome, outcome);
      expect(result.message, isNotEmpty);
      c.dispose();
    }
  });

  test('motor indisponível (503), rede e matrícula desconhecida', () async {
    var c = activeController((_) async => http.Response(jsonEncode({'outcome': 'engine_unavailable'}), 503));
    expect(await c.verifyFace('100', Uint8List(1)), isA<FaceUnavailable>());
    c.dispose();
    c = activeController((_) async => throw http.ClientException('rede'));
    expect(await c.verifyFace('100', Uint8List(1)), isA<FaceUnavailable>());
    c.dispose();
    c = activeController((_) async => http.Response('{}', 404));
    expect(await c.verifyFace('999', Uint8List(1)), isA<FaceDenied>());
    c.dispose();
  });

  test('credencial revogada durante a verificação desativa o tablet', () async {
    final store = MemoryTokenStore()..value = StoredCredential(token: '7.s', issuedAt: DateTime.now());
    final c = activeController((_) async => http.Response('{}', 401), store: store);
    expect(await c.verifyFace('100', Uint8List(1)), isA<FaceUnavailable>());
    expect(c.state, DeviceState.revoked);
    expect(await store.read(), isNull);
    c.dispose();
  });

  test('marcação envia a identificação facial e a de exceção no corpo', () async {
    final bodies = <Map<String, dynamic>>[];
    final c = activeController((r) async {
      bodies.add(jsonDecode(r.body) as Map<String, dynamic>);
      return http.Response(jsonEncode(punchOk), 201);
    });
    await c.punch('100', identification: {'method': 'face', 'verification_id': 12, 'verification_token': 'signed-token'});
    await c.punch('200', identification: {'method': 'authorized_exception', 'code': '12345678'});
    expect(bodies[0]['identification'], {'method': 'face', 'verification_id': 12, 'verification_token': 'signed-token'});
    expect(bodies[1]['identification'], {'method': 'authorized_exception', 'code': '12345678'});
    c.dispose();
  });

  test('escopo informa o modo facial', () {
    final scope = DeviceScope.fromJson({
      'name': 'T',
      'company': {'name': 'E'},
      'unit': {'name': 'U'},
      'identification_mode': 'face',
    });
    expect(scope.requiresFace, isTrue);
    expect(DeviceScope.fromJson({'name': 'T', 'company': {'name': 'E'}, 'unit': {'name': 'U'}}).requiresFace, isFalse);
  });
}
