"""Contrato de integração com o motor biométrico especializado.

O produto NÃO implementa algoritmo biométrico. Um motor real (ver docs/avaliacao-motor-biometrico.md) é
um adaptador desta interface, registrado em `settings.BIOMETRIC_ENGINES`. Imagens existem apenas em
memória durante a chamada; o que persiste é o template, sempre criptografado.
"""

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
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
    template: bytes = field(repr=False)
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
    # Como a vivacidade é avaliada: "simulated" (simulador), "motion_challenge_v2" (desafio básico, não
    # certificado) ou "certified" (motor com avaliação independente, p.ex. ISO/IEC 30107-3).
    liveness_method = "none"

    def check_ready(self) -> None:
        """Levanta `EngineUnavailable` se o motor não consegue trabalhar agora (ex.: modelo ausente)."""
        return None  # padrão: pronto (motores com dependências externas sobrescrevem)

    @abstractmethod
    def enroll(self, images: list[bytes]) -> EnrollResult: ...

    @abstractmethod
    def verify(
        self,
        template: bytes,
        probe: bytes,
        frames: tuple[bytes, ...] = (),
        steps: tuple[str, ...] | None = None,
    ) -> VerifyResult:
        """`frames`: quadros adicionais do desafio de vivacidade; `steps`: a sequência pedida pelo servidor
        (`probe` é o passo 0 e `frames` são os seguintes). Podem ser ignorados pelo motor."""


class SimulatorEngine(BiometricEngine):
    """APENAS TESTES. Não analisa rosto algum e não prova nada sobre eficácia ou antifraude.

    - cadastro: aceita bytes JPEG/PNG; o "template" é o SHA-256 da primeira imagem;
    - verificação: casa quando a imagem é idêntica; qualquer imagem contendo `SPOOF` simula ataque.
    """

    name = "simulator"
    version = "0"
    is_simulator = True
    liveness_method = "simulated"

    @staticmethod
    def _require_debug():
        if not (settings.DEBUG and settings.BIOMETRIC_ALLOW_SIMULATOR):
            raise EngineUnavailable("Simulador não permitido.")

    @staticmethod
    def _is_image(data: bytes) -> bool:
        return data.startswith(b"\xff\xd8\xff") or data.startswith(b"\x89PNG\r\n\x1a\n")

    def enroll(self, images):
        self._require_debug()
        if not images or not all(self._is_image(i) for i in images):
            raise PoorQuality("Imagem inválida.")
        if b"BLUR" in images[0]:
            raise PoorQuality("Imagem sem qualidade suficiente.")
        return EnrollResult(template=b"SIM1" + hashlib.sha256(images[0]).digest(), quality=1.0)

    def verify(self, template, probe, frames=(), steps=None):
        self._require_debug()
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
    engine = import_string(path)()
    if engine.is_simulator and not (settings.DEBUG and settings.BIOMETRIC_ALLOW_SIMULATOR):
        raise EngineUnavailable("Simulador não permitido.")
    return engine
