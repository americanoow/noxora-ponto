import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:noxora_ponto_tablet/api_client.dart';

void main() {
  for (final body in ['null', '{}', '[]', '{"status":"falha"}', '<html>']) {
    test('rejeita health inválido: $body', () async {
      final client = ApiClient(client: MockClient((_) async => http.Response(body, 200)));
      addTearDown(client.close);
      expect(await client.fetchStatus(), isA<ApiError>());
    });
  }

  for (final body in ['null', '{}', '{"database":"ok"}', '{"status":"ok","database":"falha"}']) {
    test('rejeita ready inválido: $body', () async {
      final client = ApiClient(client: MockClient((request) async => http.Response(
        request.url.path.contains('health') ? '{"status":"ok"}' : body, 200,
      )));
      addTearDown(client.close);
      expect(await client.fetchStatus(), isA<ApiError>());
    });
  }

  test('falha de rede vira estado de erro', () async {
    final client = ApiClient(client: MockClient((_) async => throw http.ClientException('rede')));
    addTearDown(client.close);
    expect(await client.fetchStatus(), isA<ApiError>());
  });
}
