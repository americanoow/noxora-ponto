"""Motor biométrico real: OpenCV YuNet (detecção) + SFace (reconhecimento 1:1), no servidor.

Modelos do OpenCV Zoo (YuNet: MIT; SFace: Apache-2.0), baixados por `manage.py fetch_face_models` para
`BIOMETRIC_MODEL_DIR` e conferidos por SHA-256 antes do uso. O produto não treina nem altera os modelos.

Vivacidade: **desafio de movimento básico** (`motion_challenge_v2`). O tablet envia, além da captura
principal, quadros em que o trabalhador vira levemente a cabeça. Exige-se o mesmo rosto em todos os
quadros e variação real de pose (geometria olhos/nariz). Isso barra foto impressa ou imagem estática,
mas **não é detecção de ataque certificada** (ISO/IEC 30107-3): vídeo reproduzido em tela ou máscara
podem passar. Por isso a empresa precisa aceitar explicitamente esse nível (`face_liveness_policy`).

Limiares (`BIOMETRIC_MATCH_THRESHOLD`) seguem a referência do OpenCV para SFace (cosseno 0,363) e
**precisam de calibração** com a população real (FAR/FRR, viés demográfico).
"""

import hashlib
import os
import threading
from pathlib import Path

from django.conf import settings

from .engines import BiometricEngine, EngineUnavailable, EnrollResult, PoorQuality, VerifyResult

# Limite de pixels decodificados (evita "bomba" de descompressão em PNG pequeno). Antes do import do cv2.
os.environ.setdefault("OPENCV_IO_MAX_IMAGE_PIXELS", str(4096 * 4096))

MODELS = {
    "detector": (
        "face_detection_yunet_2023mar.onnx",
        "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
        "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
        "face_detection_yunet/face_detection_yunet_2023mar.onnx",
    ),
    "recognizer": (
        "face_recognition_sface_2021dec.onnx",
        "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
        "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
        "face_recognition_sface/face_recognition_sface_2021dec.onnx",
    ),
}

TEMPLATE_MAGIC = b"SF1\x00"
EMBEDDING_SIZE = 128
LIVENESS_METHOD = "motion_challenge_v2"
MAX_SIDE = 960  # imagens maiores são reduzidas antes da detecção
MIN_FACE_PX = 80  # rosto menor que isto (lado do retângulo) não tem qualidade
MIN_DETECTION_SCORE = 0.85
MIN_SHARPNESS = 25.0  # variância do Laplaciano na região do rosto

_verified_files: set[str] = set()
_verify_lock = threading.Lock()
_local = threading.local()


def model_dir() -> Path:
    return Path(settings.BIOMETRIC_MODEL_DIR)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def model_path(kind: str) -> str:
    filename, expected, _ = MODELS[kind]
    path = model_dir() / filename
    key = str(path)
    with _verify_lock:
        if key not in _verified_files:
            if not path.is_file() or _sha256(path) != expected:
                raise EngineUnavailable("Modelo facial ausente ou adulterado.")
            _verified_files.add(key)
    return key


def _cv():
    try:
        import cv2
        import numpy as np
    except ImportError:  # pragma: no cover - depende do ambiente
        raise EngineUnavailable("OpenCV não instalado.") from None
    return cv2, np


class _Models:
    """Detector e reconhecedor por thread (as classes do OpenCV não são seguras entre threads)."""

    def __init__(self):
        cv2, _ = _cv()
        self.detector = cv2.FaceDetectorYN.create(model_path("detector"), "", (320, 320), 0.6, 0.3, 50)
        self.recognizer = cv2.FaceRecognizerSF.create(model_path("recognizer"), "")


def _models() -> _Models:
    models = getattr(_local, "models", None)
    if models is None:
        models = _local.models = _Models()
    return models


class OpenCVFaceEngine(BiometricEngine):
    name = "opencv-sface"
    version = "sface21-yunet23-1"
    liveness_method = LIVENESS_METHOD

    # ---- etapas isoladas (substituíveis nos testes) ----

    def _decode(self, data: bytes):
        cv2, np = _cv()
        if not (data.startswith(b"\xff\xd8\xff") or data.startswith(b"\x89PNG\r\n\x1a\n")):
            raise PoorQuality("Formato de imagem não aceito.")
        image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise PoorQuality("Imagem ilegível.")
        h, w = image.shape[:2]
        scale = min(1.0, MAX_SIDE / max(h, w))
        if scale < 1.0:
            image = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        return image

    def _detect(self, image):
        """Linhas YuNet: x, y, w, h, 5 pontos (olhos dir./esq., nariz, boca dir./esq.), score."""
        models = _models()
        h, w = image.shape[:2]
        models.detector.setInputSize((w, h))
        _, faces = models.detector.detect(image)
        return [] if faces is None else [list(map(float, row)) for row in faces]

    def _embed(self, image, face):
        _, np = _cv()
        models = _models()
        aligned = models.recognizer.alignCrop(image, np.array(face, dtype=np.float32))
        feature = models.recognizer.feature(aligned).flatten().astype(np.float32)
        norm = float(np.linalg.norm(feature))
        if norm == 0:
            raise PoorQuality("Rosto sem características suficientes.")
        return feature / norm

    def _sharpness(self, image, face) -> float:
        cv2, _ = _cv()
        x, y, w, h = (int(max(v, 0)) for v in face[:4])
        crop = image[y : y + h, x : x + w]
        if crop.size == 0:
            return 0.0
        return float(cv2.Laplacian(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())

    # ---- regras ----

    def _single_face(self, data: bytes):
        image = self._decode(data)
        faces = [f for f in self._detect(image) if f[14] >= MIN_DETECTION_SCORE]
        if len(faces) != 1:
            raise PoorQuality("É preciso exatamente um rosto na imagem.")
        face = faces[0]
        if min(face[2], face[3]) < MIN_FACE_PX:
            raise PoorQuality("Rosto pequeno demais: aproxime-se da câmera.")
        if self._sharpness(image, face) < MIN_SHARPNESS:
            raise PoorQuality("Imagem tremida ou sem foco.")
        return image, face

    @staticmethod
    def yaw_proxy(face) -> float:
        """Deslocamento horizontal do nariz até o meio dos olhos, dividido pela distância entre eles.

        Perto de 0 com o rosto de frente; muda de sinal ao virar a cabeça. Foto parada mantém o valor.
        """
        right_x, left_x, nose_x = face[4], face[6], face[8]
        eye_distance = abs(left_x - right_x)
        if eye_distance < 1:
            return 0.0
        return (nose_x - (right_x + left_x) / 2) / eye_distance

    @staticmethod
    def similarity(a, b) -> float:
        _, np = _cv()
        return float(np.dot(a, b))

    @staticmethod
    def _pack(vector) -> bytes:
        _, np = _cv()
        return TEMPLATE_MAGIC + np.asarray(vector, dtype="<f4").tobytes()

    @staticmethod
    def _unpack(template: bytes):
        _, np = _cv()
        if (
            not template.startswith(TEMPLATE_MAGIC)
            or len(template) != len(TEMPLATE_MAGIC) + 4 * EMBEDDING_SIZE
        ):
            raise EngineUnavailable("Template incompatível com este motor.")
        return np.frombuffer(template[len(TEMPLATE_MAGIC) :], dtype="<f4")

    def enroll(self, images):
        _, np = _cv()
        if not images:
            raise PoorQuality("Envie ao menos uma imagem.")
        features, qualities = [], []
        for data in images:
            image, face = self._single_face(data)
            features.append(self._embed(image, face))
            qualities.append(face[14])
        threshold = settings.BIOMETRIC_MATCH_THRESHOLD
        for i in range(len(features)):
            for j in range(i + 1, len(features)):
                if self.similarity(features[i], features[j]) < threshold:
                    raise PoorQuality("As imagens do cadastro não parecem ser da mesma pessoa.")
        mean = np.mean(np.stack(features), axis=0)
        mean = mean / float(np.linalg.norm(mean))
        return EnrollResult(template=self._pack(mean), quality=round(min(qualities), 3))

    def verify(self, template, probe, frames=(), steps=None):
        stored = self._unpack(template)
        threshold = settings.BIOMETRIC_MATCH_THRESHOLD
        image, face = self._single_face(probe)
        score = self.similarity(stored, self._embed(image, face))
        matched = score >= threshold
        if not frames:
            return VerifyResult(matched=matched, score=round(score, 4), liveness="not_performed")
        failed = VerifyResult(matched=matched, score=round(score, 4), liveness="failed")
        # Sem a sequência pedida pelo servidor (ou com quadros a mais/menos) não há prova de vivacidade.
        if steps is None or len(steps) != 1 + len(frames) or steps[0] != "center":
            return failed
        if len({hashlib.sha256(f).digest() for f in (probe, *frames)}) != 1 + len(frames):
            return failed
        yaws = [self.yaw_proxy(face)]
        for frame in frames:
            try:
                f_image, f_face = self._single_face(frame)
            except PoorQuality:
                return failed
            # Todos os quadros precisam ser da mesma pessoa cadastrada (impede trocar o rosto no meio).
            if self.similarity(stored, self._embed(f_image, f_face)) < threshold:
                return failed
            yaws.append(self.yaw_proxy(f_face))
        # Cada quadro precisa estar do lado pedido, em relação ao primeiro (de frente). Um vídeo gravado
        # antes não conhece a sequência sorteada agora.
        minimum = settings.BIOMETRIC_LIVENESS_MIN_YAW_DELTA
        left = settings.BIOMETRIC_YAW_LEFT_SIGN
        for step, yaw in zip(steps[1:], yaws[1:], strict=True):
            delta = yaw - yaws[0]
            if step == "center":
                ok = abs(delta) < minimum / 2
            elif step in ("left", "right"):
                ok = delta * (left if step == "left" else -left) >= minimum
            else:
                ok = False
            if not ok:
                return failed
        return VerifyResult(matched=matched, score=round(score, 4), liveness="passed")
