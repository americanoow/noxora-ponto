"""Motor OpenCV: regras (com detector/reconhecedor substituídos) e integração real opcional.

A integração real roda quando `BIOMETRIC_MODEL_DIR` tem os modelos e `NOXORA_TEST_FACE_IMAGE` aponta
para uma foto de rosto (não versionada). Sem isso é ignorada: não prova eficácia biométrica.
"""

import base64
import datetime
import os
import uuid
from pathlib import Path

import numpy as np
import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.biometrics import engines, engines_opencv
from apps.biometrics.engines_opencv import OpenCVFaceEngine
from apps.biometrics.models import VerificationAttempt
from apps.devices import services as device_services
from apps.devices.models import Device
from apps.operations import services as ops
from apps.operations.models import Employee, Unit
from apps.timeclock.models import TimeRecord

PNG = b"\x89PNG\r\n\x1a\n"


def face_row(*, yaw=0.0, size=150, score=0.95):
    """Linha no formato YuNet com olhos a 60 px e nariz deslocado por `yaw` (fração da distância)."""
    x, y = 100.0, 100.0
    rx, lx = x + 45, x + 105
    nose = (rx + lx) / 2 + yaw * (lx - rx)
    return [x, y, size, size, rx, y + 60, lx, y + 60, nose, y + 90, rx + 5, y + 120, lx - 5, y + 120, score]


def unit_vec(seed):
    v = np.random.default_rng(seed).normal(size=128).astype(np.float32)
    return v / np.linalg.norm(v)


class FakeEngine(OpenCVFaceEngine):
    """Cada imagem é `PNG + nome`; o roteiro diz rostos e embedding de cada nome."""

    script: dict = {}

    def _decode(self, data):
        if not data.startswith(PNG):
            raise engines.PoorQuality("Formato")
        return data[len(PNG) :].decode()

    def _detect(self, image):
        return self.script[image]["faces"]

    def _embed(self, image, face):
        return self.script[image]["vec"]

    def _sharpness(self, image, face):
        return self.script[image].get("sharp", 100.0)


def img(name):
    return PNG + name.encode()


@pytest.fixture
def engine():
    e = FakeEngine()
    pessoa, outra = unit_vec(1), unit_vec(2)
    proxima = pessoa + 0.05 * unit_vec(3)
    proxima /= np.linalg.norm(proxima)
    e.script = {
        "frente": {"faces": [face_row()], "vec": pessoa},
        "frente2": {"faces": [face_row(yaw=0.02)], "vec": proxima},
        "virado": {"faces": [face_row(yaw=0.25)], "vec": proxima},
        "outra": {"faces": [face_row()], "vec": outra},
        "outra_virada": {"faces": [face_row(yaw=0.25)], "vec": outra},
        "duas": {"faces": [face_row(), face_row()], "vec": pessoa},
        "nenhum": {"faces": [], "vec": pessoa},
        "pequeno": {"faces": [face_row(size=40)], "vec": pessoa},
        "borrado": {"faces": [face_row()], "vec": pessoa, "sharp": 1.0},
        "fraco": {"faces": [face_row(score=0.5)], "vec": pessoa},
    }
    for i in range(1, 4):  # quadros distintos do desafio: esquerda = yaw +, direita = yaw -
        e.script[f"esq{i}"] = {"faces": [face_row(yaw=0.25 + i * 0.01)], "vec": proxima}
        e.script[f"dir{i}"] = {"faces": [face_row(yaw=-0.25 - i * 0.01)], "vec": proxima}
        e.script[f"cen{i}"] = {"faces": [face_row(yaw=0.01 * i)], "vec": proxima}
    return e


def test_cadastro_e_verificacao_sem_quadros_nao_avalia_vivacidade(engine):
    template = engine.enroll([img("frente"), img("frente2")]).template
    assert template.startswith(engines_opencv.TEMPLATE_MAGIC)
    result = engine.verify(template, img("frente2"))
    assert result.matched and result.liveness == "not_performed"
    assert not engine.verify(template, img("outra")).matched


@pytest.mark.parametrize("nome", ["duas", "nenhum", "pequeno", "borrado", "fraco"])
def test_qualidade_insuficiente(engine, nome):
    with pytest.raises(engines.PoorQuality):
        engine.enroll([img(nome)])


def test_cadastro_com_pessoas_diferentes_e_recusado(engine):
    with pytest.raises(engines.PoorQuality):
        engine.enroll([img("frente"), img("outra")])


def frames_for(steps):
    return tuple(
        img(f"{'esq' if s == 'left' else 'dir' if s == 'right' else 'cen'}{i}")
        for i, s in enumerate(steps[1:], 1)
    )


def test_desafio_de_movimento_segue_a_sequencia_pedida(engine):
    template = engine.enroll([img("frente")]).template
    steps = ("center", "left", "right", "left")
    passou = engine.verify(template, img("frente2"), frames_for(steps), steps)
    assert passou.matched and passou.liveness == "passed"
    # Sequência trocada: quem gravou "esquerda, direita, esquerda" não passa se pedirem outra ordem.
    outra = ("center", "right", "left", "right")
    assert engine.verify(template, img("frente2"), frames_for(steps), outra).liveness == "failed"
    # Sem a sequência pedida pelo servidor não há prova de vivacidade.
    assert engine.verify(template, img("frente2"), frames_for(steps)).liveness == "failed"
    # Quantidade de quadros diferente da pedida.
    assert engine.verify(template, img("frente2"), frames_for(steps)[:2], steps).liveness == "failed"
    # Foto parada: a pose não muda.
    assert (
        engine.verify(template, img("frente2"), (img("frente"),) * 1, ("center", "left")).liveness == "failed"
    )
    # Mesmo arquivo repetido em todos os passos.
    assert (
        engine.verify(template, img("frente2"), (img("esq1"), img("esq1"), img("esq1")), steps).liveness
        == "failed"
    )
    # Troca de pessoa no meio do desafio.
    assert (
        engine.verify(
            template, img("frente2"), (img("outra_virada"), img("dir2"), img("esq3")), steps
        ).liveness
        == "failed"
    )
    # Quadro sem rosto.
    assert (
        engine.verify(template, img("frente2"), (img("nenhum"), img("dir2"), img("esq3")), steps).liveness
        == "failed"
    )
    # O primeiro passo precisa ser "de frente".
    assert (
        engine.verify(template, img("frente2"), frames_for(steps), ("left", *steps[1:])).liveness == "failed"
    )


def test_sentido_espelhado_e_configuravel(engine, settings):
    template = engine.enroll([img("frente")]).template
    steps = ("center", "left", "right", "left")
    settings.BIOMETRIC_YAW_LEFT_SIGN = -1  # imagem espelhada: a mesma captura já não é "esquerda"
    assert engine.verify(template, img("frente2"), frames_for(steps), steps).liveness == "failed"


def test_template_de_outro_motor_e_recusado(engine):
    with pytest.raises(engines.EngineUnavailable):
        engine.verify(b"SIM1" + b"x" * 32, img("frente"))


def test_yaw_proxy():
    assert OpenCVFaceEngine.yaw_proxy(face_row()) == pytest.approx(0)
    assert OpenCVFaceEngine.yaw_proxy(face_row(yaw=0.3)) == pytest.approx(0.3)


def test_modelo_ausente_ou_adulterado(tmp_path, settings):
    settings.BIOMETRIC_MODEL_DIR = str(tmp_path)
    engines_opencv._verified_files.clear()
    with pytest.raises(engines.EngineUnavailable):
        engines_opencv.model_path("detector")
    (tmp_path / engines_opencv.MODELS["detector"][0]).write_bytes(b"adulterado")
    with pytest.raises(engines.EngineUnavailable):
        engines_opencv.model_path("detector")


def test_decodificacao_recusa_formato_e_lixo():
    e = OpenCVFaceEngine()
    with pytest.raises(engines.PoorQuality):
        e._decode(b"GIF89a....")
    with pytest.raises(engines.PoorQuality):
        e._decode(b"\xff\xd8\xff\xe0" + b"lixo")


# ---------- Política de vivacidade da empresa (fluxo completo com o motor substituído) ----------


@pytest.fixture
def opencv_world(tenant_a, settings, engine):
    settings.DEBUG = True
    settings.BIOMETRIC_ENGINE = "fake-opencv"
    settings.BIOMETRIC_ENGINES = {**settings.BIOMETRIC_ENGINES, "fake-opencv": "x"}
    import apps.biometrics.engines as engines_module

    original = engines_module.get_engine
    engines_module.get_engine = lambda: engine
    company = tenant_a.company
    company.identification_mode = "face"
    company.save()
    unit = Unit.objects.create(company=company, name="Centro")
    device = Device.objects.create(company=company, unit=unit, name="Tablet")
    code, _ = device_services.new_activation_code(device)
    device, token = device_services.activate(code)
    employee = Employee.objects.create(company=company, registration="1", full_name="Maria")
    ops.assign_unit(employee, company, unit, None, datetime.date(2020, 1, 1))
    admin = tenant_a.client("company_admin")
    base = f"/api/companies/{company.pk}/employees/{employee.pk}/biometric/"
    assert (
        admin.post(
            base + "consent/", {"policy_version": "v1", "evidence_ref": "Termo 01"}, format="json"
        ).status_code
        == 201
    )
    b64 = lambda data: base64.b64encode(data).decode()  # noqa: E731
    assert admin.post(base + "enroll/", {"images": [b64(img("frente"))]}, format="json").status_code == 201
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Device {token}")
    yield tenant_a, client, b64
    engines_module.get_engine = original


def _challenge(client):
    r = client.post("/api/device/face/challenge/", {}, format="json")
    assert r.status_code == 201
    return r.json()


def _verify_and_punch(client, b64, frames=None, *, challenge=None, send_challenge=True):
    """`frames=None`: segue o desafio emitido; lista: envia exatamente esses quadros."""
    challenge = challenge or (_challenge(client) if frames is None or send_challenge else None)
    if frames is None:
        frames = [f"{'esq' if s == 'left' else 'dir'}{i}" for i, s in enumerate(challenge["steps"][1:], 1)]
    payload = {"registration": "1", "image": b64(img("frente2")), "frames": [b64(img(f)) for f in frames]}
    if send_challenge and challenge:
        payload["challenge_id"] = challenge["challenge_id"]
    r = client.post("/api/device/face/verify/", payload, format="json")
    body = r.json()
    punch = None
    if body.get("outcome") == "success":
        punch = client.post(
            "/api/device/punches/",
            {
                "registration": "1",
                "client_event_id": str(uuid.uuid4()),
                "identification": {
                    "method": "face",
                    "verification_id": body["verification_id"],
                    "verification_token": body["verification_token"],
                },
            },
            format="json",
        )
    return body, punch


def test_politica_certificada_recusa_desafio_basico(opencv_world):
    _, client, b64 = opencv_world
    body, punch = _verify_and_punch(client, b64)
    assert body["outcome"] == "success" and body["liveness"] == "passed"
    assert body["liveness_accepted"] is False
    assert punch.status_code == 400 and not TimeRecord.objects.exists()
    assert VerificationAttempt.objects.get().liveness_method == "motion_challenge_v2"


def test_politica_basica_aceita_desafio_e_auditoria(opencv_world):
    tenant, client, b64 = opencv_world
    admin = tenant.client("company_admin")
    r = admin.patch(
        f"/api/companies/{tenant.company.pk}/identification/",
        {"face_liveness_policy": "basic_challenge"},
        format="json",
    )
    assert r.status_code == 200 and r.json()["face_liveness_policy"] == "basic_challenge"
    body, punch = _verify_and_punch(client, b64)
    assert "liveness_accepted" not in body and punch.status_code == 201
    assert TimeRecord.objects.get().identification_method == "face"
    # Sem quadros não há prova de vivacidade: nem a política básica aceita.
    body, punch = _verify_and_punch(client, b64, [], send_challenge=False)
    assert body["liveness"] == "not_performed" and punch.status_code == 400


def test_desafio_e_imprevisivel_de_uso_unico_e_do_proprio_tablet(opencv_world):
    tenant, client, b64 = opencv_world
    admin = tenant.client("company_admin")
    admin.patch(
        f"/api/companies/{tenant.company.pk}/identification/",
        {"face_liveness_policy": "basic_challenge"},
        format="json",
    )
    sequences = {tuple(_challenge(client)["steps"]) for _ in range(25)}
    assert len(sequences) > 1  # a sequência varia entre desafios
    assert all(s[0] == "center" and {"left", "right"} <= set(s) and len(s) == 4 for s in sequences)
    # Uso único: repetir o MESMO envio com o mesmo desafio reprova na vivacidade.
    challenge = _challenge(client)
    first, _ = _verify_and_punch(client, b64, challenge=challenge)
    assert first["liveness"] == "passed"
    replay, punch = _verify_and_punch(client, b64, challenge=challenge)
    assert replay["liveness"] == "failed" and punch is None
    # Sequência diferente da pedida: reprova (mesmo com rosto certo).
    other = _challenge(client)
    wrong = ["dir1" if s == "left" else "esq1" for s in other["steps"][1:]]
    wrong = [f"{n[:3]}{i}" for i, n in enumerate(wrong, 1)]
    body, _ = _verify_and_punch(client, b64, wrong, challenge=other)
    assert body["liveness"] == "failed"
    # Desafio vencido ou inexistente: reprova.
    from apps.biometrics.models import LivenessChallenge

    old = _challenge(client)
    LivenessChallenge.objects.filter(pk=old["challenge_id"]).update(
        expires_at=timezone.now() - datetime.timedelta(seconds=1)
    )
    assert _verify_and_punch(client, b64, challenge=old)[0]["liveness"] == "failed"
    ghost = {"challenge_id": 999999, "steps": ["center", "left", "right", "left"]}
    assert _verify_and_punch(client, b64, challenge=ghost)[0]["liveness"] == "failed"
    # Desafio emitido para outro tablet não vale.
    other_device = Device.objects.create(
        company=tenant.company, unit=Unit.objects.filter(company=tenant.company).first(), name="Outro"
    )
    foreign = LivenessChallenge.objects.create(
        company=tenant.company,
        device=other_device,
        steps=["center", "left", "right", "left"],
        expires_at=timezone.now() + datetime.timedelta(seconds=30),
    )
    stolen = {"challenge_id": foreign.pk, "steps": foreign.steps}
    assert _verify_and_punch(client, b64, challenge=stolen)[0]["liveness"] == "failed"


def test_gestor_nao_altera_politica_de_vivacidade(opencv_world):
    tenant, _, _ = opencv_world
    r = tenant.client("manager").patch(
        f"/api/companies/{tenant.company.pk}/identification/",
        {"face_liveness_policy": "basic_challenge"},
        format="json",
    )
    assert r.status_code == 403


def test_quadros_demais_sao_recusados(opencv_world):
    _, client, b64 = opencv_world
    r = client.post(
        "/api/device/face/verify/",
        {"registration": "1", "image": b64(img("frente2")), "frames": [b64(img("esq1"))] * 5},
        format="json",
    )
    assert r.status_code == 400


# ---------- Integração real (opcional) ----------

_IMAGE = os.environ.get("NOXORA_TEST_FACE_IMAGE", "")


@pytest.mark.skipif(
    not _IMAGE or not Path(_IMAGE).is_file(), reason="sem foto de teste (NOXORA_TEST_FACE_IMAGE)"
)
def test_integracao_real_com_modelos(settings):
    settings.BIOMETRIC_MODEL_DIR = os.environ.get("BIOMETRIC_MODEL_DIR", settings.BIOMETRIC_MODEL_DIR)
    import cv2

    engine = OpenCVFaceEngine()
    try:
        engines_opencv.model_path("recognizer")
    except engines.EngineUnavailable:
        pytest.skip("modelos ausentes")
    data = Path(_IMAGE).read_bytes()
    template = engine.enroll([data]).template
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    _, recompressed = cv2.imencode(".jpg", cv2.GaussianBlur(image, (3, 3), 0), [cv2.IMWRITE_JPEG_QUALITY, 70])
    result = engine.verify(template, recompressed.tobytes(), (data,))
    assert result.matched and result.score > 0.8
    assert result.liveness == "failed"  # mesma foto: sem movimento


def test_motor_sem_modelos_libera_a_matricula_como_alternativa(tmp_path, settings):
    from apps.biometrics import engines_opencv

    settings.BIOMETRIC_MODEL_DIR = str(tmp_path)  # pasta vazia: modelos ausentes
    engines_opencv._verified_files.clear()
    with pytest.raises(engines.EngineUnavailable):
        engines_opencv.OpenCVFaceEngine().check_ready()
