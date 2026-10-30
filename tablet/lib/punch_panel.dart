import 'dart:async';

import 'package:flutter/material.dart';

import 'device_controller.dart';
import 'face_capture.dart';
import 'offline_queue.dart';
import 'theme.dart';

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
        style: const TextStyle(
          fontSize: 88,
          fontWeight: FontWeight.w700,
          letterSpacing: -2,
          fontFeatures: tabularFigures,
        ),
      );
}

const _kinds = <String, String>{
  '': 'Não informar',
  'entry': 'Entrada',
  'break_start': 'Saída para o intervalo',
  'break_end': 'Volta do intervalo',
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
  Widget build(BuildContext context) {
    final requiresFace = widget.controller.scope?.requiresFace ?? false;
    return ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 560),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Center(child: ClockText()),
          const SizedBox(height: 4),
          Center(child: _DateText()),
          const SizedBox(height: 8),
          Center(child: QueueStatus(controller: widget.controller)),
          const SizedBox(height: 20),
          TextField(
            controller: _registration,
            enabled: !_busy,
            style: const TextStyle(fontSize: 28, fontWeight: FontWeight.w700),
            decoration: const InputDecoration(
              labelText: 'Matrícula',
              prefixIcon: Icon(Icons.badge_outlined, size: 28),
            ),
            onSubmitted: (_) => _submit(),
          ),
          const SizedBox(height: 16),
          const Text('Tipo (opcional)', style: TextStyle(fontSize: 15, color: NoxoraColors.ink2)),
          const SizedBox(height: 8),
          Wrap(
            spacing: 10,
            runSpacing: 10,
            children: [
              for (final e in _kinds.entries)
                ChoiceChip(
                  label: Text(e.value),
                  selected: _kind == e.key,
                  showCheckmark: false,
                  labelStyle: TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.w600,
                    color: _kind == e.key ? Colors.white : NoxoraColors.ink,
                  ),
                  onSelected: _busy ? null : (_) => setState(() => _kind = e.key),
                ),
            ],
          ),
          if (requiresFace) ...[
            const SizedBox(height: 24),
            FilledButton.icon(
              key: const Key('botao-face'),
              onPressed: _busy ? null : _faceAndPunch,
              icon: const Icon(Icons.face_retouching_natural, size: 28),
              label: const Text('Reconhecer rosto e registrar'),
            ),
            if (_faceMessage != null)
              Padding(
                padding: const EdgeInsets.only(top: 12),
                child: Text(
                  _faceMessage!,
                  textAlign: TextAlign.center,
                  style: const TextStyle(fontSize: 17),
                ),
              ),
            const SizedBox(height: 20),
            _HelpBox(
              exceptionCode: _exceptionCode,
              enabled: !_busy,
            ),
          ],
          const SizedBox(height: 16),
          requiresFace
              ? OutlinedButton(
                  key: const Key('botao-registrar'),
                  onPressed: _busy ? null : _submit,
                  child: Text(_busy ? 'Registrando…' : 'Registrar com código de exceção'),
                )
              : FilledButton(
                  key: const Key('botao-registrar'),
                  onPressed: _busy ? null : _submit,
                  child: Text(_busy ? 'Registrando…' : 'Registrar ponto'),
                ),
          const SizedBox(height: 20),
          _OutcomeView(outcome: _outcome),
        ],
      ),
    );
  }
}

class _DateText extends StatelessWidget {
  static const _weekdays = [
    'segunda-feira', 'terça-feira', 'quarta-feira', 'quinta-feira', 'sexta-feira', 'sábado', 'domingo',
  ];
  static const _months = [
    'janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro',
    'outubro', 'novembro', 'dezembro',
  ];

  @override
  Widget build(BuildContext context) {
    final n = DateTime.now();
    return Text(
      '${_weekdays[n.weekday - 1]}, ${n.day} de ${_months[n.month - 1]}',
      style: const TextStyle(fontSize: 20, color: NoxoraColors.ink2),
    );
  }
}

/// Caminho de ajuda e exceção: acessível sem esconder o código de exceção emitido por um responsável.
class _HelpBox extends StatelessWidget {
  const _HelpBox({required this.exceptionCode, required this.enabled});
  final TextEditingController exceptionCode;
  final bool enabled;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.all(18),
        decoration: BoxDecoration(
          color: NoxoraColors.bgAlt,
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: NoxoraColors.line),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Row(children: [
            Icon(Icons.help_outline, color: NoxoraColors.ink2),
            SizedBox(width: 10),
            Text('Preciso de ajuda', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
          ]),
          const SizedBox(height: 8),
          const Text(
            'Sem reconhecimento? Peça a um responsável um código de exceção.',
            style: TextStyle(fontSize: 16, color: NoxoraColors.ink2),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: exceptionCode,
            enabled: enabled,
            keyboardType: TextInputType.number,
            maxLength: 8,
            style: const TextStyle(fontSize: 22, letterSpacing: 2),
            decoration: const InputDecoration(labelText: 'Código de exceção (8 dígitos)'),
          ),
        ]),
      );
}

/// Resultado da tentativa. "Ponto registrado" aparece só depois que o servidor confirma a gravação;
/// o que ficou apenas no tablet é mostrado como "guardado", nunca como confirmado.
class _OutcomeView extends StatelessWidget {
  const _OutcomeView({required this.outcome});
  final PunchOutcome? outcome;

  @override
  Widget build(BuildContext context) {
    final o = outcome;
    if (o == null) return const SizedBox.shrink();
    return switch (o) {
      PunchRecorded() => _ResultCard(
          color: NoxoraColors.accent,
          soft: NoxoraColors.accentSoft,
          icon: Icons.check_circle,
          title: o.duplicate ? 'Ponto já registrado' : 'Ponto registrado',
          lines: [
            o.workerName,
            'Confirmado pelo servidor · registro nº ${o.nsr}',
            o.occurredAt,
            'Código ${o.hash.length > 12 ? o.hash.substring(0, 12) : o.hash}…',
          ],
        ),
      PunchQueued() => _ResultCard(
          color: NoxoraColors.warn,
          soft: NoxoraColors.warnSoft,
          icon: Icons.save_outlined,
          title: 'Registro guardado neste tablet',
          lines: [
            'Horário do aparelho: ${_clock(o.deviceTime)}',
            'Ainda não confirmado pelo servidor. O número do registro e o comprovante só existem depois que o tablet reconectar.',
          ],
        ),
      PunchRejected() => _ResultCard(
          color: NoxoraColors.danger,
          soft: NoxoraColors.dangerSoft,
          icon: Icons.error_outline,
          title: o.message,
          lines: const [],
        ),
      PunchUnconfirmed() => _ResultCard(
          color: NoxoraColors.warn,
          soft: NoxoraColors.warnSoft,
          icon: Icons.sync_problem,
          title: o.message,
          lines: const [],
        ),
    };
  }
}

class _ResultCard extends StatelessWidget {
  const _ResultCard({
    required this.color,
    required this.soft,
    required this.icon,
    required this.title,
    required this.lines,
  });
  final Color color;
  final Color soft;
  final IconData icon;
  final String title;
  final List<String> lines;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.all(20),
        decoration: BoxDecoration(color: soft, borderRadius: BorderRadius.circular(16)),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Icon(icon, color: color, size: 40),
          const SizedBox(width: 16),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(title, style: TextStyle(fontSize: 24, fontWeight: FontWeight.w800, color: color)),
              for (final l in lines)
                Padding(
                  padding: const EdgeInsets.only(top: 6),
                  child: Text(l, style: const TextStyle(fontSize: 17, fontFeatures: tabularFigures)),
                ),
            ]),
          ),
        ]),
      );
}

String _clock(DateTime t) {
  String two(int n) => n.toString().padLeft(2, '0');
  return '${two(t.hour)}:${two(t.minute)}:${two(t.second)}';
}

const _rejectReasons = <String, String>{
  'invalid': 'dados inválidos',
  'offline_not_allowed': 'a empresa não permite registro sem conexão',
  'unsupported_identification': 'identificação não aceita sem conexão',
  'unknown_registration': 'matrícula não encontrada',
  'too_old': 'registro antigo demais',
};

/// Pendências da fila sem conexão: quantos registros aguardam envio, recusas que exigem uma pessoa e fila ilegível.
class QueueStatus extends StatelessWidget {
  const QueueStatus({super.key, required this.controller});
  final DeviceController controller;

  @override
  Widget build(BuildContext context) {
    final queue = controller.queue;
    final pending = queue.pendingCount;
    final rejected = queue.items.where((i) => i.state == QueuedState.rejected).toList();
    if (pending == 0 && rejected.isEmpty && !queue.corrupt) return const SizedBox.shrink();
    final offline = controller.state == DeviceState.offline;
    return Column(mainAxisSize: MainAxisSize.min, children: [
      if (queue.corrupt)
        const Text(
          'A fila de registros deste tablet estava ilegível e foi preservada para análise. Procure o administrador.',
          style: TextStyle(color: NoxoraColors.danger, fontSize: 16),
        ),
      if (pending > 0)
        Row(mainAxisSize: MainAxisSize.min, children: [
          const StatusDot(color: NoxoraColors.warn, hollow: true),
          const SizedBox(width: 10),
          Text(
            offline
                ? 'Sem conexão · $pending registro(s) aguardando envio'
                : '$pending registro(s) aguardando envio',
            style: const TextStyle(color: NoxoraColors.warn, fontSize: 17, fontWeight: FontWeight.w700),
          ),
          TextButton(onPressed: controller.syncPending, child: const Text('Enviar agora')),
        ]),
      for (final item in rejected)
        Row(mainAxisSize: MainAxisSize.min, children: [
          Flexible(
            child: Text(
              'Matrícula ${item.registration}: recusada (${_rejectReasons[item.reason] ?? item.reason}). '
              'Procure o administrador.',
              style: const TextStyle(color: NoxoraColors.danger, fontSize: 16),
            ),
          ),
          TextButton(onPressed: () => controller.acknowledgeRejected(item.eventId), child: const Text('Ciente')),
        ]),
    ]);
  }
}
