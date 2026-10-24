import 'dart:async';

import 'package:flutter/material.dart';

import 'api_client.dart';
import 'device_controller.dart';
import 'offline_queue.dart';
import 'punch_panel.dart';
import 'token_store.dart';

void main() => runApp(const NoxoraApp());

class NoxoraApp extends StatelessWidget {
  const NoxoraApp({super.key, this.client, this.deviceController});
  final ApiClient? client;
  final DeviceController? deviceController;

  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'Noxora Ponto',
        theme: ThemeData(useMaterial3: true, colorSchemeSeed: Colors.indigo),
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
        appBar: AppBar(title: const Text('Noxora Ponto')),
        body: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                FutureBuilder<ApiStatus>(
                  future: _status,
                  builder: (context, snapshot) {
                    if (snapshot.connectionState != ConnectionState.done) {
                      return const Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [CircularProgressIndicator(), SizedBox(height: 16), Text('Verificando a API…')],
                      );
                    }
                    final result = snapshot.data;
                    if (result is ApiOk) {
                      return Text('API disponível (saúde: ${result.health}, banco: ${result.database}).');
                    }
                    final message = result is ApiError ? result.message : 'Falha inesperada.';
                    return Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(message),
                        const SizedBox(height: 16),
                        FilledButton(onPressed: _retry, child: const Text('Tentar novamente')),
                      ],
                    );
                  },
                ),
                const SizedBox(height: 32),
                DevicePanel(controller: _device),
              ],
            ),
          ),
        ),
      );
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
              return const Text('Verificando o dispositivo…');
            case DeviceState.active:
              return Column(mainAxisSize: MainAxisSize.min, children: [
                Text('Tablet "${c.scope?.name}" — ${c.scope?.company} / ${c.scope?.unit}'),
                const SizedBox(height: 16),
                PunchPanel(controller: c),
              ]);
            case DeviceState.offline:
              final canPunchOffline = c.scope?.allowsOfflinePunch ?? false;
              return Column(mainAxisSize: MainAxisSize.min, children: [
                Text(c.message ?? 'Sem conexão.'),
                const SizedBox(height: 8),
                FilledButton(onPressed: c.heartbeat, child: const Text('Tentar novamente')),
                QueueStatus(controller: c),
                if (canPunchOffline) ...[
                  const SizedBox(height: 16),
                  const Text(
                    'Modo offline: a marcação será guardada neste tablet e enviada ao reconectar.',
                    style: TextStyle(color: Colors.orange),
                  ),
                  PunchPanel(controller: c),
                ],
              ]);
            case DeviceState.unactivated:
            case DeviceState.revoked:
              return Column(mainAxisSize: MainAxisSize.min, children: [
                if (c.message != null) Text(c.message!),
                QueueStatus(controller: c),
                const Text('Digite o código de ativação gerado no painel.'),
                const SizedBox(height: 8),
                SizedBox(
                  width: 260,
                  child: TextField(
                    controller: _code,
                    textCapitalization: TextCapitalization.characters,
                    decoration: const InputDecoration(labelText: 'Código de ativação'),
                  ),
                ),
                const SizedBox(height: 8),
                FilledButton(onPressed: () {
                  final code = _code.text;
                  _code.clear();
                  c.activate(code);
                }, child: const Text('Ativar tablet')),
              ]);
          }
        },
      );
}
