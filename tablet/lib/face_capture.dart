import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'package:camera/camera.dart';
import 'package:flutter/material.dart';

/// Câmera usada na verificação facial. Abstraída para os testes (sem hardware).
abstract class FaceCamera {
  Future<void> start();
  Future<Uint8List> capture();
  Widget preview();
  Future<void> stop();
}

typedef FaceCameraFactory = FaceCamera Function();

/// Câmera frontal do Android pelo plugin `camera`. As imagens ficam só em memória: nada é gravado no aparelho
/// (o arquivo temporário do plugin é lido e apagado na hora).
class DeviceFaceCamera implements FaceCamera {
  CameraController? _controller;

  @override
  Future<void> start() async {
    final cameras = await availableCameras();
    if (cameras.isEmpty) throw StateError('Nenhuma câmera disponível.');
    final front = cameras.firstWhere(
      (c) => c.lensDirection == CameraLensDirection.front,
      orElse: () => cameras.first,
    );
    final controller = CameraController(front, ResolutionPreset.medium, enableAudio: false,
        imageFormatGroup: ImageFormatGroup.jpeg);
    await controller.initialize();
    _controller = controller;
  }

  @override
  Future<Uint8List> capture() async {
    final controller = _controller;
    if (controller == null) throw StateError('Câmera não iniciada.');
    final file = await controller.takePicture();
    final bytes = await file.readAsBytes();
    try {
      await File(file.path).delete();
    } catch (_) {
      // Melhor esforço: o diretório é temporário e privado do aplicativo.
    }
    return bytes;
  }

  @override
  Widget preview() {
    final controller = _controller;
    if (controller == null || !controller.value.isInitialized) return const SizedBox.shrink();
    return CameraPreview(controller);
  }

  @override
  Future<void> stop() async {
    final controller = _controller;
    _controller = null;
    await controller?.dispose();
  }
}

/// Resultado da captura: imagem principal e quadros do desafio de movimento.
class FaceCaptureResult {
  const FaceCaptureResult(this.image, this.frames);
  final Uint8List image;
  final List<Uint8List> frames;
}

/// Passo do desafio: instrução mostrada e tempo para o trabalhador se posicionar antes da foto.
class ChallengeStep {
  const ChallengeStep(this.instruction, this.delay);
  final String instruction;
  final Duration delay;
}

/// Texto de cada passo sorteado pelo servidor. Quem decide se o movimento foi o pedido é o servidor.
ChallengeStep stepFromServer(String step, Duration delay) => ChallengeStep(
      switch (step) {
        'left' => 'Vire levemente o rosto para a ESQUERDA',
        'right' => 'Vire levemente o rosto para a DIREITA',
        _ => 'Olhe para a câmera',
      },
      delay,
    );

const defaultChallenge = <ChallengeStep>[
  ChallengeStep('Olhe para a câmera', Duration(milliseconds: 1200)),
  ChallengeStep('Vire levemente o rosto para a ESQUERDA', Duration(milliseconds: 1400)),
  ChallengeStep('Agora vire levemente para a DIREITA', Duration(milliseconds: 1400)),
];

/// Tela de captura: mostra a câmera e conduz o desafio. Fecha com [FaceCaptureResult] ou `null` (cancelado
/// ou falha da câmera).
class FaceCaptureView extends StatefulWidget {
  const FaceCaptureView({super.key, required this.camera, this.steps = defaultChallenge});
  final FaceCamera camera;
  final List<ChallengeStep> steps;

  @override
  State<FaceCaptureView> createState() => _FaceCaptureViewState();
}

class _FaceCaptureViewState extends State<FaceCaptureView> {
  String _instruction = 'Preparando a câmera…';
  String? _error;
  bool _ready = false;
  bool _cancelled = false;

  @override
  void initState() {
    super.initState();
    unawaited(_run());
  }

  Future<void> _run() async {
    final shots = <Uint8List>[];
    try {
      await widget.camera.start();
      if (!mounted || _cancelled) return;
      setState(() => _ready = true);
      for (final step in widget.steps) {
        if (!mounted || _cancelled) return;
        setState(() => _instruction = step.instruction);
        await Future<void>.delayed(step.delay);
        if (!mounted || _cancelled) return;
        shots.add(await widget.camera.capture());
      }
      if (!mounted || _cancelled) return;
      Navigator.of(context).pop(FaceCaptureResult(shots.first, shots.sublist(1)));
    } catch (_) {
      if (mounted) {
        setState(() => _error = 'Não foi possível usar a câmera. Use o código de exceção com um responsável.');
      }
    } finally {
      await widget.camera.stop();
    }
  }

  void _cancel() {
    _cancelled = true;
    Navigator.of(context).pop();
  }

  /// A moldura só orienta posição e luz. Quem decide se há uma pessoa presente é o motor biométrico
  /// no servidor; nenhuma animação desta tela comprova presença física.
  @override
  Widget build(BuildContext context) => Scaffold(
        backgroundColor: const Color(0xFF1F2422),
        body: SafeArea(
          child: Column(children: [
            const Padding(
              padding: EdgeInsets.fromLTRB(24, 20, 24, 0),
              child: Text(
                'Fique de frente, com boa luz, e deixe o rosto dentro da moldura.',
                textAlign: TextAlign.center,
                style: TextStyle(color: Color(0xFFD9DDD9), fontSize: 18),
              ),
            ),
            Expanded(
              child: Center(
                child: _error != null
                    ? Padding(
                        padding: const EdgeInsets.all(24),
                        child: Text(_error!, style: const TextStyle(color: Colors.white, fontSize: 22)),
                      )
                    : _ready
                        ? Container(
                            decoration: const BoxDecoration(
                              shape: BoxShape.circle,
                              border: Border.fromBorderSide(
                                BorderSide(color: Color(0xFF8FB8A8), width: 5),
                              ),
                            ),
                            padding: const EdgeInsets.all(8),
                            child: ClipOval(
                              child: SizedBox(width: 320, height: 400, child: widget.camera.preview()),
                            ),
                          )
                        : const CircularProgressIndicator(),
              ),
            ),
            Padding(
              padding: const EdgeInsets.all(24),
              child: Text(
                _error == null ? _instruction : '',
                key: const Key('instrucao-face'),
                textAlign: TextAlign.center,
                style: const TextStyle(color: Colors.white, fontSize: 32, fontWeight: FontWeight.w700),
              ),
            ),
            Padding(
              padding: const EdgeInsets.only(bottom: 24),
              child: OutlinedButton(
                onPressed: _cancel,
                style: OutlinedButton.styleFrom(
                  foregroundColor: Colors.white,
                  side: const BorderSide(color: Color(0xFF8FB8A8)),
                  minimumSize: const Size(200, 60),
                ),
                child: const Text('Cancelar'),
              ),
            ),
          ]),
        ),
      );
}
