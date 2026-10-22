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
  static const _tokenKey = 'device_token';
  static const _issuedKey = 'device_token_issued_at';

  @override
  Future<StoredCredential?> read() async {
    try {
      final token = await _storage.read(key: _tokenKey);
      final issued = await _storage.read(key: _issuedKey);
      if (token == null || token.isEmpty) return null;
      return StoredCredential(
        token: token,
        issuedAt: DateTime.tryParse(issued ?? '') ?? DateTime.fromMillisecondsSinceEpoch(0, isUtc: true),
      );
    } catch (_) {
      // Falha de leitura (ex.: ambiente sem Keystore) equivale a "sem credencial".
      return null;
    }
  }

  @override
  Future<void> write(StoredCredential credential) async {
    await _storage.write(key: _tokenKey, value: credential.token);
    await _storage.write(key: _issuedKey, value: credential.issuedAt.toUtc().toIso8601String());
  }

  @override
  Future<void> clear() async {
    await _storage.delete(key: _tokenKey);
    await _storage.delete(key: _issuedKey);
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
