import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Credencial do dispositivo emitida pelo servidor, com a data de emissão (para rotação).
class StoredCredential {
  const StoredCredential({required this.token, required this.issuedAt});
  final String token;
  final DateTime issuedAt;
}

abstract class TokenStore {
  Future<StoredCredential?> read();
  Future<void> write(StoredCredential credential);
  Future<void> clear();
}

/// Armazenamento protegido no Android (Keystore, via EncryptedSharedPreferences).
/// A credencial nunca vai para logs, SharedPreferences comum ou arquivos do app.
class SecureTokenStore implements TokenStore {
  SecureTokenStore([FlutterSecureStorage? storage])
      : _storage = storage ??
            const FlutterSecureStorage(
              aOptions: AndroidOptions(encryptedSharedPreferences: true),
            );

  final FlutterSecureStorage _storage;
  static const _credentialKey = 'device_credential_v1';

  @override
  Future<StoredCredential?> read() async {
    final raw = await _storage.read(key: _credentialKey);
    if (raw == null) return null;
    final value = jsonDecode(raw) as Map<String, dynamic>;
    final token = value['token'] as String;
    if (token.isEmpty) throw const FormatException('Credencial vazia.');
    return StoredCredential(token: token, issuedAt: DateTime.parse(value['issued_at'] as String));
  }

  @override
  Future<void> write(StoredCredential credential) async {
    await _storage.write(key: _credentialKey, value: jsonEncode({
      'token': credential.token,
      'issued_at': credential.issuedAt.toUtc().toIso8601String(),
    }));
  }

  @override
  Future<void> clear() async {
    await _storage.delete(key: _credentialKey);
  }
}

/// Somente para testes.
class MemoryTokenStore implements TokenStore {
  StoredCredential? value;

  @override
  Future<StoredCredential?> read() async => value;

  @override
  Future<void> write(StoredCredential credential) async => value = credential;

  @override
  Future<void> clear() async => value = null;
}
