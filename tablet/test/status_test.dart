import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:noxora_ponto_tablet/api_client.dart';
import 'package:noxora_ponto_tablet/device_controller.dart';
import 'package:noxora_ponto_tablet/main.dart';
import 'package:noxora_ponto_tablet/token_store.dart';

void main() {
  testWidgets('mostra conectado quando o sistema responde', (tester) async {
    final client = ApiClient(
      baseUrl: 'http://teste',
      client: MockClient((request) async => http.Response(
            request.url.path.contains('health') ? '{"status":"ok"}' : '{"status":"ok","database":"ok"}',
            200,
          )),
    );
    final device = DeviceController(store: MemoryTokenStore());
    await tester.pumpWidget(NoxoraApp(client: client, deviceController: device));
    expect(find.text('Verificando a conexão…'), findsOneWidget);
    await tester.pumpAndSettle();
    expect(find.text('Conectado'), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
    device.dispose();
    client.close();
  });

  testWidgets('mostra falha quando os dados estão indisponíveis', (tester) async {
    final client = ApiClient(
      baseUrl: 'http://teste',
      client: MockClient((request) async =>
          request.url.path.contains('health') ? http.Response('{"status":"ok"}', 200) : http.Response('{}', 503)),
    );
    final device = DeviceController(store: MemoryTokenStore());
    await tester.pumpWidget(NoxoraApp(client: client, deviceController: device));
    await tester.pumpAndSettle();
    expect(find.textContaining('não consegue acessar os dados'), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
    device.dispose();
    client.close();
  });
}
