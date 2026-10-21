import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:noxora_ponto_tablet/api_client.dart';
import 'package:noxora_ponto_tablet/main.dart';

void main() {
  testWidgets('mostra sucesso quando a API responde', (tester) async {
    final client = ApiClient(
      baseUrl: 'http://teste',
      client: MockClient((request) async => http.Response(
            request.url.path.contains('health') ? '{"status":"ok"}' : '{"status":"ok","database":"ok"}',
            200,
          )),
    );
    await tester.pumpWidget(NoxoraApp(client: client));
    expect(find.text('Verificando a API…'), findsOneWidget);
    await tester.pumpAndSettle();
    expect(find.textContaining('API disponível'), findsOneWidget);
  });

  testWidgets('mostra falha quando o banco está indisponível', (tester) async {
    final client = ApiClient(
      baseUrl: 'http://teste',
      client: MockClient((request) async =>
          request.url.path.contains('health') ? http.Response('{"status":"ok"}', 200) : http.Response('{}', 503)),
    );
    await tester.pumpWidget(NoxoraApp(client: client));
    await tester.pumpAndSettle();
    expect(find.textContaining('banco está indisponível'), findsOneWidget);
  });
}
