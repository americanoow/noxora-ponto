"""Contrato de integração com o motor biométrico especializado.

O produto NÃO implementa algoritmo biométrico. Um motor real (ver docs/avaliacao-motor-biometrico.md) é
um adaptador desta interface, registrado em `settings.BIOMETRIC_ENGINES`. Imagens existem apenas em
memória durante a chamada; o que persiste é o template, sempre criptografado.
"""

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

from django.conf import settings
from django.utils.module_loading import import_string

Liveness = Literal["passed", "failed", "not_performed"]


class EngineError(Exception):
    pass


class EngineUnavailable(EngineError):
    """Motor ausente, não configurado ou fora do ar."""


class PoorQuality(EngineError):
    """Imagem sem qualidade suficiente (sem rosto, borrada, escura...)."""


@dataclass(frozen=True)
class EnrollResult:
    template: bytes
    quality: float | None = None


@dataclass(frozen=True)
class VerifyResult:
    matched: bool
    score: float | None
    liveness: Liveness


class BiometricEngine(ABC):
    name: str
    version: str
    is_simulator = False

    @abstractmethod
    def enroll(self, images: list[bytes]) -> EnrollResult: ...

    @abstractmethod
    def verify(self, template: bytes, probe: bytes) -> VerifyResult: ...


class SimulatorEngine(BiometricEngine):
    """APENAS TESTES. Não analisa rosto algum e não prova nada sobre eficácia ou antifraude.

    - cadastro: aceita bytes JPEG/PNG; o "template" é o SHA-256 da primeira imagem;
    - verificação: casa quando a imagem é idêntica; qualquer imagem contendo `SPOOF` simula ataque.
    """

    name = "simulator"
    version = "0"
    is_simulator = True

    @staticmethod
    def _is_image(data: bytes) -> bool:
        return data.startswith(b"\xff\xd8\xff") or data.startswith(b"\x89PNG\r\n\x1a\n")

    def enroll(self, images):
        if not images or not all(self._is_image(i) for i in images):
            raise PoorQuality("Imagem inválida.")
        if b"BLUR" in images[0]:
            raise PoorQuality("Imagem sem qualidade suficiente.")
        return EnrollResult(template=b"SIM1" + hashlib.sha256(images[0]).digest(), quality=1.0)

    def verify(self, template, probe):
        if not self._is_image(probe):
            raise PoorQuality("Imagem inválida.")
        if b"BLUR" in probe:
            raise PoorQuality("Imagem sem qualidade suficiente.")
        if b"SPOOF" in probe:
            return VerifyResult(matched=False, score=None, liveness="failed")
        matched = template == b"SIM1" + hashlib.sha256(probe).digest()
        return VerifyResult(matched=matched, score=1.0 if matched else 0.0, liveness="passed")


def get_engine() -> BiometricEngine:
    name = settings.BIOMETRIC_ENGINE
    path = settings.BIOMETRIC_ENGINES.get(name)
    if not name or not path:
        raise EngineUnavailable("Motor biométrico não configurado.")
    return import_string(path)()
