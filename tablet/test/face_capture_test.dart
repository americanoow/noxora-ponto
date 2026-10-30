import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:noxora_ponto_tablet/device_controller.dart';
import 'package:noxora_ponto_tablet/face_capture.dart';
import 'package:noxora_ponto_tablet/punch_panel.dart';
import 'package:noxora_ponto_tablet/token_store.dart';

class FakeCamera implements FaceCamera {
  FakeCamera({this.fail = false});
  final bool fail;
  int shots = 0;
  bool stopped = false;

  @override
  Future<void> start() async {
    if (fail) throw StateError('sem câmera');
  }

  @override
  Future<Uint8List> capture() async => Uint8List.fromList([0xff, 0xd8, ++shots]);

  @override
  Widget preview() => const SizedBox(width: 10, height: 10);

  @override
  Future<void> stop() async => stopped = true;
}

const faceScope = {
  'name': 'Tablet',
  'company': {'name': 'Empresa'},
  'unit': {'name': 'Centro'},
  'identification_mode': 'face',
};

const fastSteps = [
  ChallengeStep('Olhe', Duration(milliseconds: 10)),
  ChallengeStep('Esquerda', Duration(milliseconds: 10)),
  ChallengeStep('Direita', Duration(milliseconds: 10)),
];

Future<DeviceController> activeController(List<http.Request> requests,
    {Map<String, dynamic> verifyBody = const {
      'outcome': 'success',
      'liveness': 'passed',
      'verification_id': 7,
      'verification_token': 'tok',
    }}) async {
  final store = MemoryTokenStore()..value = StoredCredential(token: '1.x', issuedAt: DateTime.now());
  final c = DeviceController(
    store: store,
    baseUrl: 'http://teste',
    client: MockClient((r) async {
      requests.add(r);
      if (r.url.path.endsWith('heartbeat/')) {
        return http.Response(jsonEncode({...faceScope, 'server_time': DateTime.now().toUtc().toIso8601String()}), 200);
      }
      if (r.url.path.endsWith('face/verify/')) return http.Response(jsonEncode(verifyBody), 200);
      if (r.url.path.endsWith('punches/')) {
        return http.Response(
            jsonEncode({
              'duplicate': false,
              'receipt': {
                'nsr': 5,
                'worker': {'name': 'Maria'},
                'occurred_at': '2026-10-27T08:00:00-03:00',
                'hash_sha256': 'a' * 64,
              },
            }),
            201);
      }
      return http.Response('{}', 404);
    }),
  );
  await c.init();
  return c;
}

Widget app(DeviceController c, FaceCameraFactory factory) => MaterialApp(
      home: Scaffold(
        body: SingleChildScrollView(child: PunchPanel(controller: c, cameraFactory: factory, challenge: fastSteps)),
      ),
    );


/// Tablet de verdade é grande; o padrão do teste (800x600) cortaria os botões fora da tela.
void bigScreen(WidgetTester t) {
  t.view.physicalSize = const Size(1280, 1800);
  t.view.devicePixelRatio = 1.0;
  addTearDown(t.view.resetPhysicalSize);
  addTearDown(t.view.resetDevicePixelRatio);
}

void main() {
  testWidgets('desafio captura 3 quadros, verifica e registra com o token facial', (tester) async {
    bigScreen(tester);
    final requests = <http.Request>[];
    final c = await tester.runAsync(() => activeController(requests));
    final camera = FakeCamera();
    await tester.pumpWidget(app(c!, () => camera));
    await tester.enterText(find.byType(TextField).first, '100');
    await tester.tap(find.byKey(const Key('botao-face')));
    await tester.pumpAndSettle();
    await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 200)));
    await tester.pumpAndSettle();
    expect(camera.shots, 3);
    expect(camera.stopped, isTrue);
    final verify = requests.firstWhere((r) => r.url.path.endsWith('face/verify/'));
    final body = jsonDecode(verify.body) as Map<String, dynamic>;
    expect(body['registration'], '100');
    expect((body['frames'] as List).length, 2);
    final punch = requests.firstWhere((r) => r.url.path.endsWith('punches/'));
    expect((jsonDecode(punch.body) as Map)['identification'],
        {'method': 'face', 'verification_id': 7, 'verification_token': 'tok'});
    expect(find.text('Ponto registrado'), findsOneWidget);
    c.dispose();
  });

  testWidgets('vivacidade fora da política: não registra e orienta', (tester) async {
    bigScreen(tester);
    final requests = <http.Request>[];
    final c = await tester.runAsync(() => activeController(requests, verifyBody: const {
          'outcome': 'success',
          'liveness': 'passed',
          'liveness_accepted': false,
          'verification_id': 7,
          'verification_token': 'tok',
        }));
    await tester.pumpWidget(app(c!, FakeCamera.new));
    await tester.enterText(find.byType(TextField).first, '100');
    await tester.tap(find.byKey(const Key('botao-face')));
    await tester.pumpAndSettle();
    await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 200)));
    await tester.pumpAndSettle();
    expect(requests.where((r) => r.url.path.endsWith('punches/')), isEmpty);
    expect(find.textContaining('política da empresa'), findsOneWidget);
    c.dispose();
  });

  testWidgets('câmera indisponível não registra e sugere o código de exceção', (tester) async {
    bigScreen(tester);
    final requests = <http.Request>[];
    final c = await tester.runAsync(() => activeController(requests));
    await tester.pumpWidget(app(c!, () => FakeCamera(fail: true)));
    await tester.enterText(find.byType(TextField).first, '100');
    await tester.tap(find.byKey(const Key('botao-face')));
    await tester.pumpAndSettle();
    await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 50)));
    await tester.pumpAndSettle();
    expect(find.textContaining('código de exceção'), findsWidgets);
    await tester.tap(find.text('Cancelar'));
    await tester.pumpAndSettle();
    expect(requests.where((r) => r.url.path.endsWith('face/verify/')), isEmpty);
    expect(find.textContaining('cancelada'), findsOneWidget);
    c.dispose();
  });

  testWidgets('sem matrícula não abre a câmera', (tester) async {
    bigScreen(tester);
    final requests = <http.Request>[];
    final c = await tester.runAsync(() => activeController(requests));
    var opened = false;
    await tester.pumpWidget(app(c!, () {
      opened = true;
      return FakeCamera();
    }));
    await tester.tap(find.byKey(const Key('botao-face')));
    await tester.pumpAndSettle();
    expect(opened, isFalse);
    expect(find.text('Informe a matrícula.'), findsOneWidget);
    c.dispose();
  });
}
