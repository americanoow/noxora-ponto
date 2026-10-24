import 'dart:async';

import 'package:flutter/material.dart';

import 'device_controller.dart';
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
  const PunchPanel({super.key, required this.controller});
  final DeviceController controller;

  @override
  State<PunchPanel> createState() => _PunchPanelState();
}

class _PunchPanelState extends State<PunchPanel> {
  final _registration = TextEditingController();
  final _exceptionCode = TextEditingController();
  String _kind = '';
  PunchOutcome? _outcome;
  bool _busy = false;

  @override
  void dispose() {
    _registration.dispose();
    _exceptionCode.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _outcome = null;
    });
    final code = _exceptionCode.text.trim();
    final outcome = await widget.controller.punch(
      _registration.text,
      declaredKind: _kind,
      identification: code.isEmpty ? null : {'method': 'authorized_exception', 'code': code},
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
              initialValue: _kind,
              decoration: const InputDecoration(labelText: 'Tipo (opcional)'),
              items: [
                for (final e in _kinds.entries) DropdownMenuItem(value: e.key, child: Text(e.value)),
              ],
              onChanged: _busy ? null : (v) => setState(() => _kind = v ?? ''),
            ),
          ),
          if (widget.controller.scope?.requiresFace ?? false) ...[
            const SizedBox(height: 8),
            const SizedBox(
              width: 300,
              child: Text(
                'Esta empresa exige verificação facial. A captura pela câmera ainda não está '
                'disponível neste aplicativo; chame um responsável para obter um código de exceção.',
              ),
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
            onPressed: _busy ? null : _submit,
            child: Text(_busy ? 'Registrando…' : 'Registrar ponto'),
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
