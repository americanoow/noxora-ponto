import 'package:flutter/material.dart';

import 'api_client.dart';

void main() => runApp(const NoxoraApp());

class NoxoraApp extends StatelessWidget {
  const NoxoraApp({super.key, this.client});
  final ApiClient? client;

  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'Noxora Ponto',
        theme: ThemeData(useMaterial3: true, colorSchemeSeed: Colors.indigo),
        home: StatusPage(client: client),
      );
}

class StatusPage extends StatefulWidget {
  const StatusPage({super.key, this.client});
  final ApiClient? client;

  @override
  State<StatusPage> createState() => _StatusPageState();
}

class _StatusPageState extends State<StatusPage> {
  late final ApiClient _client = widget.client ?? ApiClient();
  late Future<ApiStatus> _status = _client.fetchStatus();

  void _retry() => setState(() => _status = _client.fetchStatus());

  @override
  void dispose() {
    if (widget.client == null) _client.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Noxora Ponto')),
        body: Center(
          child: FutureBuilder<ApiStatus>(
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
        ),
      );
}
