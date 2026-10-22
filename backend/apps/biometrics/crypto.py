"""Criptografia do template biométrico: AES-256-GCM com nonce aleatório e dados associados (AAD).

O AAD amarra o texto cifrado à empresa e ao funcionário: um template copiado para outro registro
não decifra. A chave de escrita é BIOMETRIC_ACTIVE_KEY_ID; chaves antigas continuam valendo para leitura
(rotação). Limite: a chave fica em variável de ambiente; KMS/HSM e crypto-shredding são etapa 14/15.
"""

import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings


class CryptoUnavailable(Exception):
    pass


class DecryptionFailed(Exception):
    pass


def make_aad(company_id: int, employee_id: int, engine: str) -> bytes:
    return f"noxora-biometric:v1:{company_id}:{employee_id}:{engine}".encode()


def _key(key_id: str) -> bytes:
    raw = settings.BIOMETRIC_KEYS.get(key_id)
    if not raw:
        raise CryptoUnavailable("Chave biométrica indisponível.")
    try:
        key = base64.b64decode(raw, validate=True)
        if len(key) != 32:
            raise ValueError
        return key
    except (ValueError, TypeError):
        raise CryptoUnavailable("Chave biométrica inválida.") from None


def encrypt(plaintext: bytes, aad: bytes) -> tuple[str, bytes, bytes]:
    key_id = settings.BIOMETRIC_ACTIVE_KEY_ID
    if not key_id:
        raise CryptoUnavailable("Nenhuma chave biométrica ativa configurada.")
    nonce = os.urandom(12)
    return key_id, nonce, AESGCM(_key(key_id)).encrypt(nonce, plaintext, aad)


def decrypt(key_id: str, nonce: bytes, ciphertext: bytes, aad: bytes) -> bytes:
    try:
        return AESGCM(_key(key_id)).decrypt(bytes(nonce), bytes(ciphertext), aad)
    except (InvalidTag, ValueError, TypeError):
        raise DecryptionFailed("Template não pôde ser verificado.") from None
