import 'dart:async';
import 'dart:convert';

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
