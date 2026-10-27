import 'dart:async';

import 'package:flutter/material.dart';

import 'device_controller.dart';
import 'face_capture.dart';
import 'offline_queue.dart';

/// Relógio digital com horas, minutos e segundos (Anexo IX, item 3, da Portaria MTP 671/2021).
/// O horário oficial da marcação é o do servidor; este relógio é a referência visual do trabalhador.
class ClockText extends StatefulWidget {
  const ClockText({super.key, this.now});
  final DateTime Function()? now;

  @override
  State<ClockText> createState() => _ClockTextState();
}

class _ClockTextState extends State<ClockText> {
  late DateTime _now = (widget.now ?? DateTime.now)();
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _timer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() => _now = (widget.now ?? DateTime.now)());
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  String _two(int n) => n.toString().padLeft(2, '0');

  @override
  Widget build(BuildContext context) => Text(
        '${_two(_now.hour)}:${_two(_now.minute)}:${_two(_now.second)}',
        key: const Key('relogio'),
        style: Theme.of(context).textTheme.displayMedium,
      );
}

const _kinds = <String, String>{
  '': 'Não informar o tipo',
  'entry': 'Entrada',
  'break_start': 'Início de intervalo',
  'break_end': 'Fim de intervalo',
  'exit': 'Saída',
};

/// Tela de marcação do terminal compartilhado.
class PunchPanel extends StatefulWidget {
  const PunchPanel({super.key, required this.controller, this.cameraFactory, this.challenge = defaultChallenge});
  final DeviceController controller;

  /// Câmera da verificação facial (substituível nos testes). Padrão: câmera frontal do aparelho.
  final FaceCameraFactory? cameraFactory;
  final List<ChallengeStep> challenge;

  @override
  State<PunchPanel> createState() => _PunchPanelState();
}

class _PunchPanelState extends State<PunchPanel> {
  final _registration = TextEditingController();
  final _exceptionCode = TextEditingController();
  String _kind = '';
  PunchOutcome? _outcome;
  String? _faceMessage;
  bool _busy = false;

  @override
  void dispose() {
    _registration.dispose();
    _exceptionCode.dispose();
    super.dispose();
  }

  /// Verificação facial (câmera + desafio de movimento) seguida da marcação com o token de uso único.
  Future<void> _faceAndPunch() async {
    if (_busy) return;
    final reg = _registration.text.trim();
    if (reg.isEmpty) {
      setState(() => _outcome = const PunchRejected('Informe a matrícula.'));
      return;
    }
    setState(() {
      _busy = true;
      _outcome = null;
      _faceMessage = null;
    });
    final camera = (widget.cameraFactory ?? DeviceFaceCamera.new)();
    final capture = await Navigator.of(context).push<FaceCaptureResult>(
      MaterialPageRoute(builder: (_) => FaceCaptureView(camera: camera, steps: widget.challenge)),
    );
    if (!mounted) return;
    if (capture == null) {
      setState(() {
        _busy = false;
        _faceMessage = 'Captura cancelada ou câmera indisponível.';
      });
      return;
    }
    setState(() => _faceMessage = 'Verificando o rosto…');
    final face = await widget.controller.verifyFace(reg, capture.image, frames: capture.frames);
    if (!mounted) return;
    switch (face) {
      case FaceVerified():
        setState(() => _faceMessage = null);
        await _send(face.identification);
      case FaceDenied(:final message):
      case FaceUnavailable(:final message):
        setState(() {
          _busy = false;
          _faceMessage = message;
        });
    }
  }

  Future<void> _submit() async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _outcome = null;
      _faceMessage = null;
    });
    final code = _exceptionCode.text.trim();
    await _send(code.isEmpty ? null : {'method': 'authorized_exception', 'code': code});
  }

  Future<void> _send(Map<String, dynamic>? identification) async {
    final outcome = await widget.controller.punch(
      _registration.text,
      declaredKind: _kind,
      identification: identification,
    );
    if (!mounted) return;
    setState(() {
      _busy = false;
      _outcome = outcome;
      // Só limpa a matrícula quando a tentativa se encerrou; se não houve confirmação,
      // o mesmo evento é reenviado com a mesma matrícula (sem duplicar).
      if (outcome is! PunchUnconfirmed) {
        _registration.clear();
        _exceptionCode.clear();
      }
    });
  }

  @override
  Widget build(BuildContext context) => Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const ClockText(),
          QueueStatus(controller: widget.controller),
          const SizedBox(height: 16),
          SizedBox(
            width: 300,
            child: TextField(
              controller: _registration,
              enabled: !_busy,
              decoration: const InputDecoration(labelText: 'Matrícula'),
              onSubmitted: (_) => _submit(),
            ),
          ),
          const SizedBox(height: 8),
          SizedBox(
            width: 300,
            child: DropdownButtonFormField<String>(
              isExpanded: true,
              initialValue: _kind,
              decoration: const InputDecoration(labelText: 'Tipo (opcional)'),
              items: [
                for (final e in _kinds.entries) DropdownMenuItem(value: e.key, child: Text(e.value)),
              ],
              onChanged: _busy ? null : (v) => setState(() => _kind = v ?? ''),
            ),
          ),
          if (widget.controller.scope?.requiresFace ?? false) ...[
            const SizedBox(height: 16),
            FilledButton.icon(
              key: const Key('botao-face'),
              onPressed: _busy ? null : _faceAndPunch,
              icon: const Icon(Icons.face),
              label: const Text('Reconhecer rosto e registrar'),
            ),
            if (_faceMessage != null)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: SizedBox(width: 300, child: Text(_faceMessage!, textAlign: TextAlign.center)),
              ),
            const SizedBox(height: 16),
            const SizedBox(
              width: 300,
              child: Text('Sem reconhecimento? Peça a um responsável um código de exceção.'),
            ),
            SizedBox(
              width: 300,
              child: TextField(
                controller: _exceptionCode,
                enabled: !_busy,
                keyboardType: TextInputType.number,
                maxLength: 8,
                decoration: const InputDecoration(labelText: 'Código de exceção (8 dígitos)'),
              ),
            ),
          ],
          const SizedBox(height: 16),
          FilledButton(
            key: const Key('botao-registrar'),
            onPressed: _busy ? null : _submit,
            child: Text(_busy
                ? 'Registrando…'
                : (widget.controller.scope?.requiresFace ?? false)
                    ? 'Registrar com código de exceção'
                    : 'Registrar ponto'),
          ),
          const SizedBox(height: 16),
          _OutcomeView(outcome: _outcome),
        ],
      );
}

class _OutcomeView extends StatelessWidget {
  const _OutcomeView({required this.outcome});
  final PunchOutcome? outcome;

  @override
  Widget build(BuildContext context) {
    final o = outcome;
    if (o == null) return const SizedBox.shrink();
    return switch (o) {
      PunchRecorded() => Column(children: [
          Text(o.duplicate ? 'Ponto já registrado' : 'Ponto registrado',
              style: Theme.of(context).textTheme.titleLarge),
          Text('${o.workerName} — NSR ${o.nsr}'),
          Text(o.occurredAt),
          Text('Código ${o.hash.length > 12 ? o.hash.substring(0, 12) : o.hash}…'),
        ]),
      PunchQueued() => Column(children: [
          Text('Marcação guardada neste tablet', style: Theme.of(context).textTheme.titleLarge),
          Text('Horário do aparelho: ${_clock(o.deviceTime)}'),
          const Text(
            'PENDENTE de envio. O número (NSR) e o comprovante só existem depois que o tablet reconectar.',
            style: TextStyle(color: Colors.orange),
          ),
        ]),
      PunchRejected() => Text(o.message, style: const TextStyle(color: Colors.red)),
      PunchUnconfirmed() => Text(o.message, style: const TextStyle(color: Colors.orange)),
    };
  }
}

String _clock(DateTime t) {
  String two(int n) => n.toString().padLeft(2, '0');
  return '${two(t.hour)}:${two(t.minute)}:${two(t.second)}';
}

const _rejectReasons = <String, String>{
  'invalid': 'dados inválidos',
  'offline_not_allowed': 'a empresa não permite marcação offline',
  'unsupported_identification': 'identificação não aceita offline',
  'unknown_registration': 'matrícula não encontrada',
  'too_old': 'registro antigo demais',
};

/// Pendências da fila offline: quantas aguardam envio, recusas que exigem uma pessoa e fila ilegível.
class QueueStatus extends StatelessWidget {
  const QueueStatus({super.key, required this.controller});
  final DeviceController controller;

  @override
  Widget build(BuildContext context) {
    final queue = controller.queue;
    final pending = queue.pendingCount;
    final rejected = queue.items.where((i) => i.state == QueuedState.rejected).toList();
    if (pending == 0 && rejected.isEmpty && !queue.corrupt) return const SizedBox.shrink();
    return Column(mainAxisSize: MainAxisSize.min, children: [
      if (queue.corrupt)
        const Text(
          'A fila de marcações deste tablet estava ilegível e foi preservada para análise. Procure o administrador.',
          style: TextStyle(color: Colors.red),
        ),
      if (pending > 0)
        Row(mainAxisSize: MainAxisSize.min, children: [
          Text('$pending marcação(ões) pendente(s) de envio', style: const TextStyle(color: Colors.orange)),
          TextButton(onPressed: controller.syncPending, child: const Text('Sincronizar agora')),
        ]),
      for (final item in rejected)
        Row(mainAxisSize: MainAxisSize.min, children: [
          Text(
            'Matrícula ${item.registration}: recusada (${_rejectReasons[item.reason] ?? item.reason}). '
            'Procure o administrador.',
            style: const TextStyle(color: Colors.red),
          ),
          TextButton(onPressed: () => controller.acknowledgeRejected(item.eventId), child: const Text('Ciente')),
        ]),
    ]);
  }
}
