import 'dart:async';

import 'package:flutter/material.dart';

import 'api_client.dart';
import 'device_controller.dart';
import 'offline_queue.dart';
import 'punch_panel.dart';
import 'theme.dart';
import 'token_store.dart';

void main() => runApp(const NoxoraApp());

class NoxoraApp extends StatelessWidget {
  const NoxoraApp({super.key, this.client, this.deviceController});
  final ApiClient? client;
  final DeviceController? deviceController;

  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'Noxora Ponto',
        debugShowCheckedModeBanner: false,
        theme: noxoraTheme(),
        home: StatusPage(client: client, deviceController: deviceController),
      );
}

class StatusPage extends StatefulWidget {
  const StatusPage({super.key, this.client, this.deviceController});
  final ApiClient? client;
  final DeviceController? deviceController;

  @override
  State<StatusPage> createState() => _StatusPageState();
}

class _StatusPageState extends State<StatusPage> {
  late final ApiClient _client = widget.client ?? ApiClient();
  late final DeviceController _device =
      widget.deviceController ??
      DeviceController(store: SecureTokenStore(), queueStorage: SecureQueueStorage());
  late Future<ApiStatus> _status = _client.fetchStatus();
  Timer? _heartbeat;

  @override
  void initState() {
    super.initState();
    _device.init();
    _heartbeat = Timer.periodic(const Duration(minutes: 1), (_) => _device.heartbeat());
  }

  void _retry() => setState(() => _status = _client.fetchStatus());

  @override
  void dispose() {
    _heartbeat?.cancel();
    if (widget.client == null) _client.close();
    if (widget.deviceController == null) _device.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        body: SafeArea(
          child: Column(
            children: [
              _TopBar(controller: _device, status: _status, onRetry: _retry),
              Expanded(
                child: Center(
                  child: SingleChildScrollView(
                    padding: const EdgeInsets.all(24),
                    child: DevicePanel(controller: _device),
                  ),
                ),
              ),
            ],
          ),
        ),
      );
}

/// Marca, unidade em destaque e estado da conexão. A unidade fica sempre visível para quem registra.
class _TopBar extends StatelessWidget {
  const _TopBar({required this.controller, required this.status, required this.onRetry});
  final DeviceController controller;
  final Future<ApiStatus> status;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 28, vertical: 16),
        decoration: const BoxDecoration(
          color: NoxoraColors.bgAlt,
          border: Border(bottom: BorderSide(color: NoxoraColors.line)),
        ),
        child: ListenableBuilder(
          listenable: controller,
          builder: (context, _) {
            final scope = controller.scope;
            final offline = controller.state == DeviceState.offline;
            return Row(children: [
              const _Brand(),
              const SizedBox(width: 28),
              if (controller.state == DeviceState.active || offline)
                Expanded(
                  child: Text(
                    scope == null ? '' : '${scope.unit} · ${scope.company}',
                    key: const Key('unidade'),
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w700),
                  ),
                )
              else
                const SizedBox.shrink(),
              Flexible(
                  child: offline
                  ? _ConnectionChip(
                      color: NoxoraColors.warn,
                      hollow: true,
                      label: 'Sem conexão',
                      action: TextButton(
                        onPressed: controller.heartbeat,
                        child: const Text('Tentar novamente'),
                      ),
                    )
                  : FutureBuilder<ApiStatus>(
                      future: status,
                      builder: (context, snapshot) {
                        if (snapshot.connectionState != ConnectionState.done) {
                          return const _ConnectionChip(
                            color: NoxoraColors.ink2,
                            hollow: true,
                            label: 'Verificando a conexão…',
                          );
                        }
                        final result = snapshot.data;
                        if (result is ApiOk) {
                          return const _ConnectionChip(
                            color: NoxoraColors.accent,
                            label: 'Conectado',
                          );
                        }
                        return _ConnectionChip(
                          color: NoxoraColors.danger,
                          hollow: true,
                          label: result is ApiError ? result.message : 'Falha inesperada.',
                          action: TextButton(onPressed: onRetry, child: const Text('Tentar novamente')),
                        );
                      },
                    )),
            ]);
          },
        ),
      );
}

class _Brand extends StatelessWidget {
  const _Brand();

  @override
  Widget build(BuildContext context) => Row(crossAxisAlignment: CrossAxisAlignment.baseline, textBaseline: TextBaseline.alphabetic, children: const [
        Text('Noxora', style: TextStyle(fontSize: 26, fontWeight: FontWeight.w800, letterSpacing: -0.5)),
        SizedBox(width: 2),
        StatusDot(color: NoxoraColors.accent, size: 9),
        SizedBox(width: 8),
        Text('PONTO', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, letterSpacing: 1.2, color: NoxoraColors.ink2)),
      ]);
}

class _ConnectionChip extends StatelessWidget {
  const _ConnectionChip({required this.color, required this.label, this.hollow = false, this.action});
  final Color color;
  final String label;
  final bool hollow;
  final Widget? action;

  @override
  Widget build(BuildContext context) => Row(mainAxisAlignment: MainAxisAlignment.end, children: [
        StatusDot(color: color, hollow: hollow),
        const SizedBox(width: 10),
        Flexible(child: Text(label, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600))),
        if (action != null) action!,
      ]);
}

/// Ativação do tablet por código temporário e situação do dispositivo.
class DevicePanel extends StatefulWidget {
  const DevicePanel({super.key, required this.controller});
  final DeviceController controller;

  @override
  State<DevicePanel> createState() => _DevicePanelState();
}

class _DevicePanelState extends State<DevicePanel> {
  final _code = TextEditingController();

  @override
  void dispose() {
    _code.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
        listenable: widget.controller,
        builder: (context, _) {
          final c = widget.controller;
          switch (c.state) {
            case DeviceState.loading:
              return const Text('Verificando o dispositivo…', style: TextStyle(fontSize: 18));
            case DeviceState.active:
              return PunchPanel(controller: c);
            case DeviceState.offline:
              final canPunchOffline = c.scope?.allowsOfflinePunch ?? false;
              return Column(mainAxisSize: MainAxisSize.min, children: [
                Text(c.message ?? 'Sem conexão.', style: const TextStyle(fontSize: 18)),
                const SizedBox(height: 12),
                QueueStatus(controller: c),
                if (canPunchOffline) ...[
                  const SizedBox(height: 16),
                  const _Notice(
                    'Sem conexão: o registro fica guardado neste tablet e só é confirmado quando '
                    'ele voltar a se conectar. Reconhecimento facial não funciona sem conexão.',
                  ),
                  const SizedBox(height: 16),
                  PunchPanel(controller: c),
                ],
              ]);
            case DeviceState.unactivated:
            case DeviceState.revoked:
              return ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 440),
                child: Column(mainAxisSize: MainAxisSize.min, children: [
                  if (c.message != null) ...[Text(c.message!), const SizedBox(height: 12)],
                  QueueStatus(controller: c),
                  const Text(
                    'Ativar este tablet',
                    style: TextStyle(fontSize: 28, fontWeight: FontWeight.w800, letterSpacing: -0.5),
                  ),
                  const SizedBox(height: 8),
                  const Text(
                    'Digite o código de ativação gerado no painel.',
                    textAlign: TextAlign.center,
                    style: TextStyle(fontSize: 17, color: NoxoraColors.ink2),
                  ),
                  const SizedBox(height: 20),
                  TextField(
                    controller: _code,
                    textCapitalization: TextCapitalization.characters,
                    textAlign: TextAlign.center,
                    style: const TextStyle(fontSize: 28, letterSpacing: 4, fontWeight: FontWeight.w700),
                    decoration: const InputDecoration(labelText: 'Código de ativação'),
                  ),
                  const SizedBox(height: 16),
                  SizedBox(
                    width: double.infinity,
                    child: FilledButton(
                      onPressed: () {
                        final code = _code.text;
                        _code.clear();
                        c.activate(code);
                      },
                      child: const Text('Ativar tablet'),
                    ),
                  ),
                ]),
              );
          }
        },
      );
}

class _Notice extends StatelessWidget {
  const _Notice(this.text);
  final String text;

  @override
  Widget build(BuildContext context) => Container(
        constraints: const BoxConstraints(maxWidth: 520),
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: NoxoraColors.warnSoft,
          borderRadius: BorderRadius.circular(14),
        ),
        child: Text(text, style: const TextStyle(fontSize: 16, color: NoxoraColors.warn)),
      );
}
