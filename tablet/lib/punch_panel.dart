import 'dart:async';

import 'package:flutter/material.dart';

import 'device_controller.dart';

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
  String _kind = '';
  PunchOutcome? _outcome;
  bool _busy = false;

  @override
  void dispose() {
    _registration.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() {
      _busy = true;
      _outcome = null;
    });
    final outcome = await widget.controller.punch(_registration.text, declaredKind: _kind);
    if (!mounted) return;
    setState(() {
      _busy = false;
      _outcome = outcome;
      // Só limpa a matrícula quando a tentativa se encerrou; se não houve confirmação,
      // o mesmo evento é reenviado com a mesma matrícula (sem duplicar).
      if (outcome is! PunchUnconfirmed) _registration.clear();
    });
  }

  @override
  Widget build(BuildContext context) => Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const ClockText(),
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
          Text('Código ${o.hash.substring(0, 12)}…'),
        ]),
      PunchRejected() => Text(o.message, style: const TextStyle(color: Colors.red)),
      PunchUnconfirmed() => Text(o.message, style: const TextStyle(color: Colors.orange)),
    };
  }
}
