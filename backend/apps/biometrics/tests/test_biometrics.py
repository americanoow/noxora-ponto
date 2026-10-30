import base64
import datetime
import uuid
from unittest import mock

import pytest
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.biometrics import crypto, engines, services
from apps.biometrics.models import (
    BiometricConsent,
    BiometricTemplate,
    ExceptionAuthorization,
    ExceptionBudget,
    Outcome,
    VerificationAttempt,
)
from apps.devices import services as device_services
from apps.devices.models import Device
from apps.operations import services as ops
from apps.operations.models import Employee, Unit
from apps.timeclock.models import TimeRecord

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def simulator_debug(settings):
    settings.DEBUG = True


JPEG = b"\xff\xd8\xff\xe0FOTO-DA-MARIA"
OUTRA = b"\xff\xd8\xff\xe0FOTO-DE-OUTRA-PESSOA"
SPOOF = b"\xff\xd8\xff\xe0SPOOF-FOTO-DE-FOTO"
BLUR = b"\xff\xd8\xff\xe0BLUR"


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def make_unit(company, name="Centro"):
    return Unit.objects.create(company=company, name=name)


def make_device(company, unit, name="Tablet"):
    device = Device.objects.create(company=company, unit=unit, name=name)
    code, _ = device_services.new_activation_code(device)
    return device_services.activate(code)


def tablet(token):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Device {token}")
    return client


def make_employee(company, unit, registration="1", name="Maria", active=True):
    employee = Employee.objects.create(
        company=company,
        registration=registration,
        full_name=name,
        cpf="52998224725" if registration == "1" else "",
        is_active=active,
    )
    ops.assign_unit(employee, company, unit, None, datetime.date(2020, 1, 1))
    return employee


def url(company, employee, suffix=""):
    return f"/api/companies/{company.pk}/employees/{employee.pk}/{suffix}"


def enroll_via_api(tenant, employee, image=JPEG):
    admin = tenant.client("company_admin")
    assert (
        admin.post(
            url(tenant.company, employee, "biometric/consent/"), {"policy_version": "v1"}, format="json"
        ).status_code
        == 201
    )
    r = admin.post(
        url(tenant.company, employee, "biometric/enroll/"), {"images": [b64(image)]}, format="json"
    )
    assert r.status_code == 201, r.content
    return r


@pytest.fixture
def world(tenant_a):
    unit = make_unit(tenant_a.company)
    device, token = make_device(tenant_a.company, unit)
    employee = make_employee(tenant_a.company, unit)
    return tenant_a, unit, device, tablet(token), employee


def verify(client, image=JPEG, registration="1"):
    response = client.post(
        "/api/device/face/verify/", {"registration": registration, "image": b64(image)}, format="json"
    )
    if "verification_token" in response.json():
        if not hasattr(client, "face_tokens"):
            client.face_tokens = {}
        client.face_tokens[response.json()["verification_id"]] = response.json()["verification_token"]
    return response


def punch(client, **identification):
    body = {"registration": "1", "client_event_id": str(uuid.uuid4())}
    if identification.get("method") == "face":
        vid = identification.get("verification_id")
        if isinstance(vid, int):
            identification.setdefault(
                "verification_token", getattr(client, "face_tokens", {}).get(vid, "invalid")
            )
    if identification:
        body["identification"] = identification
    return client.post("/api/device/punches/", body, format="json")


# ---------- Consentimento, cadastro e proteção do template ----------


def test_cadastro_exige_consentimento_e_nao_devolve_dados_biometricos(world):
    tenant, _, _, _, employee = world
    admin = tenant.client("company_admin")
    sem = admin.post(
        url(tenant.company, employee, "biometric/enroll/"), {"images": [b64(JPEG)]}, format="json"
    )
    assert sem.status_code == 400 and not BiometricTemplate.objects.exists()
    body = enroll_via_api(tenant, employee).json()
    assert body["template"]["engine"] == "simulator" and body["consent"]["policy_version"] == "v1"
    text = str(body).lower()
    assert all(word not in text for word in ("ciphertext", "nonce", "key_id", "sim1"))
    assert admin.get(url(tenant.company, employee, "biometric/")).json()["template"]["engine"] == "simulator"


def test_template_fica_criptografado_no_banco_e_nao_vai_para_auditoria(world):
    tenant, _, _, _, employee = world
    enroll_via_api(tenant, employee)
    template = BiometricTemplate.objects.get()
    raw = bytes(template.ciphertext)
    assert b"SIM1" not in raw and JPEG not in raw and len(raw) > 16
    assert template.key_id == "dev" and len(bytes(template.nonce)) == 12
    dump = str(list(AuditLog.objects.values())) + repr(template)
    assert "SIM1" not in dump and b64(JPEG) not in dump and raw.hex() not in dump


def test_template_copiado_para_outro_funcionario_nao_decifra(tenant_a):
    unit = make_unit(tenant_a.company)
    maria = make_employee(tenant_a.company, unit, "1")
    joao = make_employee(tenant_a.company, unit, "2", "João")
    enroll_via_api(tenant_a, maria)
    stolen = BiometricTemplate.objects.get()
    aad_joao = crypto.make_aad(tenant_a.company.pk, joao.pk, "simulator")
    with pytest.raises(crypto.DecryptionFailed):
        crypto.decrypt(stolen.key_id, stolen.nonce, stolen.ciphertext, aad_joao)
    aad_maria = crypto.make_aad(tenant_a.company.pk, maria.pk, "simulator")
    assert crypto.decrypt(stolen.key_id, stolen.nonce, stolen.ciphertext, aad_maria).startswith(b"SIM1")


def test_criptografia_rotacao_de_chave_e_chave_ausente(settings):
    import os

    settings.BIOMETRIC_KEYS = {"a": b64(os.urandom(32)), "b": b64(os.urandom(32))}
    settings.BIOMETRIC_ACTIVE_KEY_ID = "a"
    key_id, nonce, ct = crypto.encrypt(b"segredo", b"aad")
    settings.BIOMETRIC_ACTIVE_KEY_ID = "b"  # rotação: nova escrita usa "b", leitura antiga continua
    assert crypto.decrypt(key_id, nonce, ct, b"aad") == b"segredo"
    assert crypto.encrypt(b"x", b"aad")[0] == "b"
    with pytest.raises(crypto.DecryptionFailed):
        crypto.decrypt(key_id, nonce, ct, b"outro-aad")
    with pytest.raises(crypto.DecryptionFailed):
        crypto.decrypt(key_id, nonce, ct[:-1] + bytes([ct[-1] ^ 1]), b"aad")
    settings.BIOMETRIC_KEYS = {}
    with pytest.raises(crypto.CryptoUnavailable):
        crypto.decrypt("a", nonce, ct, b"aad")
    settings.BIOMETRIC_ACTIVE_KEY_ID = ""
    with pytest.raises(crypto.CryptoUnavailable):
        crypto.encrypt(b"x", b"aad")


def test_novo_cadastro_substitui_o_anterior_e_exclusao_apaga_o_conteudo(world):
    tenant, _, _, _, employee = world
    enroll_via_api(tenant, employee)
    admin = tenant.client("company_admin")
    admin.post(url(tenant.company, employee, "biometric/enroll/"), {"images": [b64(OUTRA)]}, format="json")
    assert BiometricTemplate.objects.filter(status="active").count() == 1
    old = BiometricTemplate.objects.get(status="deleted")
    assert bytes(old.ciphertext) == b"" and bytes(old.nonce) == b"" and old.delete_reason == "replaced"
    assert admin.delete(url(tenant.company, employee, "biometric/")).status_code == 200
    assert not BiometricTemplate.objects.filter(status="active").exists()
    assert all(bytes(t.ciphertext) == b"" for t in BiometricTemplate.objects.all())
    assert admin.delete(url(tenant.company, employee, "biometric/")).status_code == 404


def test_revogar_consentimento_exclui_o_template(world):
    tenant, _, _, client, employee = world
    enroll_via_api(tenant, employee)
    assert (
        tenant.client("company_admin").delete(url(tenant.company, employee, "biometric/consent/")).status_code
        == 200
    )
    assert not BiometricTemplate.objects.filter(status="active").exists()
    assert verify(client).json()["outcome"] == "no_consent"
    assert (
        tenant.client("company_admin").delete(url(tenant.company, employee, "biometric/consent/")).status_code
        == 400
    )


def test_constraints_de_unicidade_no_banco(world):
    tenant, _, _, _, employee = world
    enroll_via_api(tenant, employee)
    user = tenant.users["company_admin"]
    with pytest.raises(IntegrityError), transaction.atomic():
        BiometricConsent.objects.create(
            company=tenant.company, employee=employee, policy_version="x", granted_by=user
        )
    with pytest.raises(IntegrityError), transaction.atomic():
        BiometricTemplate.objects.create(
            company=tenant.company,
            employee=employee,
            engine="e",
            engine_version="1",
            key_id="dev",
            created_by=user,
        )


def test_imagens_invalidas_sao_rejeitadas(world):
    tenant, _, _, _, employee = world
    admin = tenant.client("company_admin")
    admin.post(url(tenant.company, employee, "biometric/consent/"), {"policy_version": "v1"}, format="json")
    path = url(tenant.company, employee, "biometric/enroll/")
    big = b64(b"\xff\xd8\xff" + b"0" * 1_100_000)
    for images in (
        None,
        [],
        "x",
        [b64(JPEG)] * 6,
        ["***nao-e-base64***"],
        [123],
        [big],
        [b64(b"texto qualquer")],
        [b64(BLUR)],
    ):
        assert admin.post(path, {"images": images}, format="json").status_code == 400, str(images)[:40]
    assert not BiometricTemplate.objects.exists()


def test_permissoes_do_painel_e_isolamento(world, tenant_b, platform_admin):
    from conftest import login_client

    tenant, unit, _, _, employee = world
    enroll_via_api(tenant, employee)
    paths = [
        ("get", "biometric/"),
        ("delete", "biometric/"),
        ("post", "biometric/consent/"),
        ("post", "biometric/enroll/"),
    ]
    for role in ("manager", "employee"):
        client = tenant.client(role)
        for method, suffix in paths:
            assert (
                getattr(client, method)(url(tenant.company, employee, suffix), {}, format="json").status_code
                == 403
            )
    for client in (tenant_b.client("company_admin"),):
        for method, suffix in paths:
            assert (
                getattr(client, method)(url(tenant.company, employee, suffix), {}, format="json").status_code
                == 404
            )
            assert (
                getattr(client, method)(
                    url(tenant_b.company, employee, suffix), {}, format="json"
                ).status_code
                == 404
            )
    admin_plat = login_client(platform_admin)
    for method, suffix in paths:
        assert (
            getattr(admin_plat, method)(url(tenant.company, employee, suffix), {}, format="json").status_code
            == 403
        )
    assert BiometricTemplate.objects.filter(status="active").count() == 1


# ---------- Verificação 1:1 ----------


def test_verificacao_bem_sucedida_registra_tentativa_sem_imagem(world):
    tenant, _, device, client, employee = world
    enroll_via_api(tenant, employee)
    r = verify(client)
    assert r.status_code == 200 and r.json()["outcome"] == "success" and r.json()["liveness"] == "passed"
    attempt = VerificationAttempt.objects.get()
    assert (
        attempt.device_id == device.pk
        and attempt.employee_id == employee.pk
        and attempt.engine == "simulator"
    )
    assert attempt.expires_at > timezone.now() and attempt.consumed_at is None
    assert b64(JPEG) not in str(list(VerificationAttempt.objects.values()))


def test_resultados_de_falha(world):
    tenant, _, _, client, employee = world
    assert verify(client).json()["outcome"] == "no_consent"
    tenant.client("company_admin").post(
        url(tenant.company, employee, "biometric/consent/"), {"policy_version": "v1"}, format="json"
    )
    assert verify(client).json()["outcome"] == "no_template"
    enroll_via_api_template_only = tenant.client("company_admin").post(
        url(tenant.company, employee, "biometric/enroll/"), {"images": [b64(JPEG)]}, format="json"
    )
    assert enroll_via_api_template_only.status_code == 201
    assert verify(client, OUTRA).json()["outcome"] == "no_match"
    assert verify(client, SPOOF).json()["outcome"] == "liveness_failed"
    assert verify(client, BLUR).json()["outcome"] == "poor_quality"
    assert "verification_id" not in verify(client, OUTRA).json()


def test_bloqueio_apos_falhas_seguidas_e_desbloqueio_por_tempo(world, settings):
    tenant, _, _, client, employee = world
    enroll_via_api(tenant, employee)
    for _ in range(settings.BIOMETRIC_LOCKOUT_FAILURES):
        assert verify(client, OUTRA).json()["outcome"] == "no_match"
    assert verify(client, JPEG).json()["outcome"] == "locked"  # mesmo a imagem correta
    VerificationAttempt.objects.update(created_at=timezone.now() - datetime.timedelta(hours=1))
    assert verify(client, JPEG).json()["outcome"] == "success"


def test_falhas_de_qualidade_nao_bloqueiam_e_sucesso_zera_a_contagem(world, settings):
    tenant, _, _, client, employee = world
    enroll_via_api(tenant, employee)
    for _ in range(10):
        assert verify(client, BLUR).json()["outcome"] == "poor_quality"
    for _ in range(settings.BIOMETRIC_LOCKOUT_FAILURES - 1):
        verify(client, OUTRA)
    assert verify(client, JPEG).json()["outcome"] == "success"
    for _ in range(settings.BIOMETRIC_LOCKOUT_FAILURES - 1):
        verify(client, OUTRA)
    assert verify(client, JPEG).json()["outcome"] == "success"


def test_matricula_fora_da_unidade_ou_de_outra_empresa_e_404_uniforme(tenant_a, tenant_b):
    unit, other = make_unit(tenant_a.company, "A"), make_unit(tenant_a.company, "B")
    _, token = make_device(tenant_a.company, unit)
    make_employee(tenant_a.company, other, "2")
    unit_b = make_unit(tenant_b.company, "A")
    make_employee(tenant_b.company, unit_b, "3")
    client = tablet(token)
    for reg in ("999", "2", "3"):
        assert verify(client, registration=reg).status_code == 404
    assert not VerificationAttempt.objects.exists()


def test_entrada_invalida_na_verificacao(world):
    *_, client, _ = world
    for body in (
        {"registration": "1"},
        {"registration": "1", "image": "***"},
        {"registration": "", "image": b64(JPEG)},
        {"registration": "1", "image": b64(b"\xff\xd8\xff" + b"0" * 1_100_000)},
    ):
        assert client.post("/api/device/face/verify/", body, format="json").status_code == 400
    assert APIClient().post(
        "/api/device/face/verify/", {"registration": "1", "image": b64(JPEG)}, format="json"
    ).status_code in (401, 403)


def test_motor_indisponivel_registra_e_retorna_503(world, settings):
    tenant, _, _, client, employee = world
    enroll_via_api(tenant, employee)
    settings.BIOMETRIC_ENGINE = ""
    r = verify(client)
    assert r.status_code == 503 and r.json()["outcome"] == "engine_unavailable"
    assert VerificationAttempt.objects.get().outcome == Outcome.ENGINE_UNAVAILABLE
    admin = tenant.client("company_admin")
    assert (
        admin.post(
            url(tenant.company, employee, "biometric/enroll/"), {"images": [b64(JPEG)]}, format="json"
        ).status_code
        == 400
    )


# ---------- Marcação com verificação facial ----------


def test_fluxo_completo_verifica_e_marca(world):
    tenant, _, _, client, employee = world
    enroll_via_api(tenant, employee)
    vid = verify(client).json()["verification_id"]
    r = punch(client, method="face", verification_id=vid)
    assert r.status_code == 201
    record = TimeRecord.objects.get()
    assert record.identification_method == "face" and record.identification_ref == str(vid)
    assert VerificationAttempt.objects.get(pk=vid).consumed_at is not None


def test_verificacao_e_de_uso_unico_expira_e_nao_serve_a_outro(world, tenant_b):
    tenant, unit, device, client, employee = world
    other = make_employee(tenant.company, unit, "2", "João")
    enroll_via_api(tenant, employee)
    vid = verify(client).json()["verification_id"]
    assert punch(client, method="face", verification_id=vid).status_code == 201
    assert punch(client, method="face", verification_id=vid).status_code == 400  # reuso
    # expirada
    vid2 = verify(client).json()["verification_id"]
    VerificationAttempt.objects.filter(pk=vid2).update(
        expires_at=timezone.now() - datetime.timedelta(seconds=1)
    )
    assert punch(client, method="face", verification_id=vid2).status_code == 400
    # de outro funcionário
    vid3 = verify(client).json()["verification_id"]
    other_body = {
        "registration": other.registration,
        "client_event_id": str(uuid.uuid4()),
        "identification": {
            "method": "face",
            "verification_id": vid3,
            "verification_token": client.face_tokens[vid3],
        },
    }
    assert client.post("/api/device/punches/", other_body, format="json").status_code == 400
    # de outro dispositivo
    _, token2 = make_device(tenant.company, unit, "Outro")
    assert (
        punch(
            tablet(token2), method="face", verification_id=vid3, verification_token=client.face_tokens[vid3]
        ).status_code
        == 400
    )
    assert TimeRecord.objects.count() == 1
    # tipos inválidos e ids inexistentes
    for bad in (None, True, "1", 10**9, [1], {"a": 1}):
        assert punch(client, method="face", verification_id=bad).status_code == 400


def test_falha_na_marcacao_nao_consome_a_verificacao(world):
    tenant, _, _, client, employee = world
    enroll_via_api(tenant, employee)
    vid = verify(client).json()["verification_id"]
    with mock.patch("apps.timeclock.services._insert", side_effect=RuntimeError("disco cheio")):
        assert punch(client, method="face", verification_id=vid).status_code == 500
    assert VerificationAttempt.objects.get(pk=vid).consumed_at is None
    assert punch(client, method="face", verification_id=vid).status_code == 201


def test_reenvio_do_mesmo_evento_devolve_a_marcacao_original(world):
    tenant, _, _, client, employee = world
    enroll_via_api(tenant, employee)
    vid = verify(client).json()["verification_id"]
    event = str(uuid.uuid4())
    body = {
        "registration": "1",
        "client_event_id": event,
        "identification": {
            "method": "face",
            "verification_id": vid,
            "verification_token": client.face_tokens[vid],
        },
    }
    first = client.post("/api/device/punches/", body, format="json")
    again = client.post(
        "/api/device/punches/", body, format="json"
    )  # token já consumido, mas o evento é o mesmo
    assert first.status_code == 201 and again.status_code == 200 and again.json()["duplicate"] is True
    assert TimeRecord.objects.count() == 1


def test_modo_facial_exige_face_ou_excecao(world):
    tenant, _, _, client, employee = world
    admin = tenant.client("company_admin")
    assert (
        admin.patch(
            f"/api/companies/{tenant.company.pk}/identification/", {"mode": "face"}, format="json"
        ).status_code
        == 200
    )
    assert punch(client).status_code == 400  # só matrícula
    assert punch(client, method="registration").status_code == 400
    assert TimeRecord.objects.count() == 0
    enroll_via_api(tenant, employee)
    vid = verify(client).json()["verification_id"]
    assert punch(client, method="face", verification_id=vid).status_code == 201


def test_modo_facial_exige_vivacidade_aprovada(world):
    tenant, _, _, client, employee = world
    enroll_via_api(tenant, employee)
    tenant.company.identification_mode = "face"
    tenant.company.save()

    class SemVivacidade(engines.SimulatorEngine):
        name = "simulator"
        is_simulator = False

        def verify(self, template, probe, frames=(), steps=None):
            return engines.VerifyResult(matched=True, score=0.9, liveness="not_performed")

    with mock.patch.object(services.engines, "get_engine", return_value=SemVivacidade()):
        vid = verify(client).json()["verification_id"]
    assert punch(client, method="face", verification_id=vid).status_code == 400
    tenant.company.identification_mode = "registration"
    tenant.company.save()
    assert punch(client, method="face", verification_id=vid).status_code == 201  # modo menos rígido aceita


def test_simulador_nao_e_aceito_fora_de_debug(world, settings):
    tenant, _, _, client, employee = world
    enroll_via_api(tenant, employee)
    vid = verify(client).json()["verification_id"]
    settings.BIOMETRIC_ALLOW_SIMULATOR = False
    assert punch(client, method="face", verification_id=vid).status_code == 400
    assert TimeRecord.objects.count() == 0


def test_configuracao_recusa_simulador_em_producao(monkeypatch):
    import runpy
    from pathlib import Path

    settings_file = Path(__file__).resolve().parents[3] / "config" / "settings.py"
    for name in ("DJANGO_DEBUG", "DJANGO_ALLOWED_HOSTS", "BIOMETRIC_KEYS", "BIOMETRIC_ACTIVE_KEY_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DJANGO_SECRET_KEY", "only-for-settings-tests-0123456789-abcdefghijklmnopqrstuvwxyz")
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/noxora_test")
    monkeypatch.setenv("BIOMETRIC_ENGINE", "simulator")
    with pytest.raises(RuntimeError, match="simulador"):
        runpy.run_path(str(settings_file))
    monkeypatch.setenv("BIOMETRIC_ENGINE", "")
    monkeypatch.setenv("BIOMETRIC_KEYS", '{"a": "curta"}')
    with pytest.raises((RuntimeError, ValueError)):  # chave base64 curta demais
        runpy.run_path(str(settings_file))


# ---------- Exceção autorizada ----------


def exception_url(company, employee):
    return url(company, employee, "identification-exceptions/")


def test_excecao_autorizada_permite_uma_marcacao_no_modo_facial(world):
    tenant, unit, _, client, employee = world
    tenant.company.identification_mode = "face"
    tenant.company.save()
    tenant.memberships["manager"].scope_units.add(unit)
    r = tenant.client("manager").post(
        exception_url(tenant.company, employee), {"reason": "Câmera danificada"}, format="json"
    )
    assert r.status_code == 201
    code, auth_id = r.json()["code"], r.json()["authorization_id"]
    assert len(code) == 8 and code.isdigit()
    assert punch(client, method="authorized_exception", code=code).status_code == 201
    record = TimeRecord.objects.get()
    assert record.identification_method == "authorized_exception"
    assert record.identification_ref == str(auth_id)
    assert punch(client, method="authorized_exception", code=code).status_code == 400  # uso único
    log = AuditLog.objects.get(action="identification.exception_authorized")
    assert log.actor_email == tenant.users["manager"].email


def test_codigo_de_excecao_so_existe_na_resposta(world):
    tenant, _, _, _, employee = world
    code = (
        tenant.client("company_admin")
        .post(exception_url(tenant.company, employee), {"reason": "Câmera danificada"}, format="json")
        .json()["code"]
    )
    auth = ExceptionAuthorization.objects.get()
    assert code not in str(auth.__dict__) and len(auth.code_hash) == 64
    assert code not in str(list(AuditLog.objects.values()))


def test_excecao_com_codigo_errado_expirado_ou_de_outro_funcionario_e_recusada(world):
    tenant, unit, device, client, employee = world
    other = make_employee(tenant.company, unit, "2", "João")
    admin = tenant.client("company_admin")
    body = admin.post(
        exception_url(tenant.company, employee), {"reason": "Sem rosto cadastrado"}, format="json"
    ).json()
    code = body["code"]
    wrong = f"{(int(code) + 1) % 10**8:08d}"
    for bad in (wrong, "1234", "abcdefgh", "１２３４５６７８", None, 12345678, True, [code], {"a": 1}):
        assert punch(client, method="authorized_exception", code=bad).status_code == 400, bad
    # o mesmo código não serve a outro funcionário
    other_body = {
        "registration": other.registration,
        "client_event_id": str(uuid.uuid4()),
        "identification": {"method": "authorized_exception", "code": code},
    }
    assert client.post("/api/device/punches/", other_body, format="json").status_code == 400
    assert TimeRecord.objects.count() == 0
    ExceptionBudget.objects.all().delete()
    ExceptionAuthorization.objects.update(expires_at=timezone.now() - datetime.timedelta(seconds=1))
    assert punch(client, method="authorized_exception", code=code).status_code == 400
    assert TimeRecord.objects.count() == 0


def test_excecao_exige_papel_escopo_motivo_e_empresa(world, tenant_b):
    tenant, unit, _, _, employee = world
    reason = {"reason": "Câmera danificada"}
    assert (
        tenant.client("employee")
        .post(exception_url(tenant.company, employee), reason, format="json")
        .status_code
        == 403
    )
    assert (
        tenant.client("manager")
        .post(exception_url(tenant.company, employee), reason, format="json")
        .status_code
        == 404
    )  # fora do escopo
    tenant.memberships["manager"].scope_units.add(unit)
    assert (
        tenant.client("manager")
        .post(exception_url(tenant.company, employee), reason, format="json")
        .status_code
        == 201
    )
    assert (
        tenant.client("company_admin")
        .post(exception_url(tenant.company, employee), {"reason": "x"}, format="json")
        .status_code
        == 400
    )
    assert (
        tenant.client("company_admin")
        .post(exception_url(tenant.company, employee), {}, format="json")
        .status_code
        == 400
    )
    assert (
        tenant_b.client("company_admin")
        .post(exception_url(tenant.company, employee), reason, format="json")
        .status_code
        == 404
    )
    assert (
        tenant_b.client("company_admin")
        .post(exception_url(tenant_b.company, employee), reason, format="json")
        .status_code
        == 404
    )
    Employee.objects.filter(pk=employee.pk).update(is_active=False)
    assert (
        tenant.client("company_admin")
        .post(exception_url(tenant.company, employee), reason, format="json")
        .status_code
        == 400
    )


# ---------- Política da empresa ----------


def test_modo_de_identificacao_permissoes_e_auditoria(tenant_a, tenant_b):
    path = f"/api/companies/{tenant_a.company.pk}/identification/"
    default = {"mode": "registration", "offline_policy": "disabled", "face_liveness_policy": "certified"}
    got = tenant_a.client("manager").get(path).json()
    assert {k: got[k] for k in default} == default and got["engine"]["name"] == "simulator"
    assert tenant_a.client("employee").get(path).status_code == 403
    assert tenant_a.client("manager").patch(path, {"mode": "face"}, format="json").status_code == 403
    assert (
        tenant_a.client("manager")
        .patch(path, {"offline_policy": "registration_only"}, format="json")
        .status_code
        == 403
    )
    for bad in (
        {"mode": "x"},
        {},
        {"mode": None},
        {"offline_policy": "x"},
        {"offline_policy": None},
        {"face_liveness_policy": "x"},
    ):
        assert tenant_a.client("company_admin").patch(path, bad, format="json").status_code == 400, bad
    body = tenant_a.client("company_admin").patch(path, {"mode": "face"}, format="json").json()
    assert body["mode"] == "face" and body["offline_policy"] == "disabled"
    log = AuditLog.objects.get(action="identification.mode_changed")
    assert log.metadata["before"] == default
    assert log.metadata["after"] == {**default, "mode": "face"}
    body = (
        tenant_a.client("company_admin")
        .patch(path, {"offline_policy": "registration_only"}, format="json")
        .json()
    )
    assert body["mode"] == "face" and body["offline_policy"] == "registration_only"
    tenant_a.company.refresh_from_db()
    assert tenant_a.company.offline_policy == "registration_only"
    assert AuditLog.objects.filter(action="identification.mode_changed").count() == 2
    for other in ({"mode": "registration"}, {"offline_policy": "disabled"}):
        assert tenant_b.client("company_admin").patch(path, other, format="json").status_code == 404


# ---------- Retenção ----------


def test_purge_exclui_somente_templates_de_inativos_antigos(tenant_a):
    unit = make_unit(tenant_a.company)
    old = make_employee(tenant_a.company, unit, "1", "Antigo")
    recent = make_employee(tenant_a.company, unit, "2", "Recente")
    active = make_employee(tenant_a.company, unit, "3", "Ativo")
    for e in (old, recent, active):
        enroll_via_api(tenant_a, e)
    now = timezone.now()
    Employee.objects.filter(pk=old.pk).update(
        is_active=False, inactivated_at=now - datetime.timedelta(days=90)
    )
    Employee.objects.filter(pk=recent.pk).update(
        is_active=False, inactivated_at=now - datetime.timedelta(days=5)
    )
    call_command("purge_biometrics", "--inactive-days", "30", "--dry-run")
    assert BiometricTemplate.objects.filter(status="active").count() == 3
    call_command("purge_biometrics", "--inactive-days", "30")
    alive = set(BiometricTemplate.objects.filter(status="active").values_list("employee_id", flat=True))
    assert alive == {recent.pk, active.pk}
    deleted = BiometricTemplate.objects.get(status="deleted", employee=old)
    assert bytes(deleted.ciphertext) == b"" and deleted.delete_reason == "retention_purge"


# Regressões da revisão adversarial.
def test_bloqueio_nao_e_deslocado_por_qualidade_ou_tentativas_bloqueadas(world):
    tenant, _, _, client, employee = world
    enroll_via_api(tenant, employee)
    for _ in range(4):
        assert verify(client, OUTRA).json()["outcome"] == "no_match"
    for _ in range(8):
        assert verify(client, BLUR).json()["outcome"] == "poor_quality"
    assert verify(client, OUTRA).json()["outcome"] == "no_match"
    for _ in range(12):
        assert verify(client).json()["outcome"] == "locked"


@pytest.mark.parametrize("action", ["biometric/consent/", "biometric/", "replace"])
def test_exclusao_revogacao_substituicao_invalidam_tokens(world, action):
    tenant, _, _, client, employee = world
    enroll_via_api(tenant, employee)
    vid = verify(client).json()["verification_id"]
    admin = tenant.client("company_admin")
    if action == "replace":
        assert (
            admin.post(
                url(tenant.company, employee, "biometric/enroll/"), {"images": [b64(JPEG)]}, format="json"
            ).status_code
            == 201
        )
    else:
        assert admin.delete(url(tenant.company, employee, action)).status_code == 200
    assert punch(client, method="face", verification_id=vid).status_code == 400
    assert not TimeRecord.objects.exists()


@pytest.mark.parametrize("debug,allow", [(False, True), (True, False), (False, False)])
def test_todas_entradas_simulador_recusadas(world, settings, debug, allow):
    tenant, _, _, client, employee = world
    enroll_via_api(tenant, employee)
    vid = verify(client).json()["verification_id"]
    settings.DEBUG, settings.BIOMETRIC_ALLOW_SIMULATOR = debug, allow
    assert verify(client).status_code == 503
    assert punch(client, method="face", verification_id=vid).status_code == 400
    with pytest.raises(engines.EngineUnavailable):
        engines.SimulatorEngine().enroll([JPEG])
    with pytest.raises(engines.EngineUnavailable):
        engines.SimulatorEngine().verify(b"template", JPEG)
    assert (
        tenant.client("company_admin")
        .post(url(tenant.company, employee, "biometric/enroll/"), {"images": [b64(JPEG)]}, format="json")
        .status_code
        == 400
    )


def test_cota_excecao_persiste_apos_rollback_e_independe_de_matricula(world):
    tenant, unit, device, client, employee = world
    for _ in range(10):
        assert punch(client, method="authorized_exception", code="00000000").status_code == 400
    other = make_employee(tenant.company, unit, "2")
    response = client.post(
        "/api/device/punches/",
        {
            "registration": other.registration,
            "client_event_id": str(uuid.uuid4()),
            "identification": {"method": "authorized_exception", "code": "00000000"},
        },
        format="json",
    )
    assert response.status_code == 429
    _, token = make_device(tenant.company, unit, "Outro")
    assert punch(tablet(token), method="authorized_exception", code="00000000").status_code == 429
    ExceptionBudget.objects.update(window_started_at=timezone.now() - datetime.timedelta(minutes=2))
    assert punch(client, method="authorized_exception", code="00000000").status_code == 400


def test_nova_excecao_invalida_anterior_e_nao_permite_cache(world):
    tenant, _, _, client, employee = world
    admin = tenant.client("company_admin")
    path = exception_url(tenant.company, employee)
    first = admin.post(path, {"reason": "Câmera quebrada"}, format="json")
    second = admin.post(path, {"reason": "Câmera quebrada"}, format="json")
    assert first["Cache-Control"] == second["Cache-Control"] == "no-store"
    assert punch(client, method="authorized_exception", code=first.json()["code"]).status_code == 400
    assert punch(client, method="authorized_exception", code=second.json()["code"]).status_code == 201


@pytest.mark.parametrize("body", [[], [1], None, True, "texto"])
def test_json_nao_objeto_rejeitado(world, body):
    tenant, _, _, client, employee = world
    import json

    assert (
        client.post("/api/device/face/verify/", json.dumps(body), content_type="application/json").status_code
        == 400
    )
    assert (
        tenant.client("company_admin")
        .post(exception_url(tenant.company, employee), json.dumps(body), content_type="application/json")
        .status_code
        == 400
    )


def test_corpo_grande_limitado_antes_do_json(world, settings):
    *_, client, _ = world
    settings.BIOMETRIC_MAX_IMAGE_BYTES = 10
    with mock.patch("apps.biometrics.security.JSONParser.parse") as parser:
        assert (
            client.post("/api/device/face/verify/", b"x" * 70000, content_type="application/json").status_code
            == 400
        )
    parser.assert_not_called()


def test_erro_nao_expoe_imagem_codigo_ou_template_em_debug(world, caplog):
    tenant, _, _, client, employee = world
    enroll_via_api(tenant, employee)
    secret = "BIOMETRIC-SECRET-SENTINEL"
    with mock.patch.object(engines.SimulatorEngine, "verify", side_effect=RuntimeError(secret)):
        response = verify(client)
    assert response.status_code == 500
    assert secret not in response.content.decode() + caplog.text
    assert b64(JPEG) not in response.content.decode() + caplog.text
    assert secret not in repr(engines.EnrollResult(secret.encode()))


def test_deploy_recusa_simulador_e_motor_sem_chave(settings):
    from apps.biometrics.checks import biometric_deployment_checks

    assert "biometrics.E001" in {e.id for e in biometric_deployment_checks(None)}
    settings.BIOMETRIC_ENGINE = "real-ainda-ausente"
    settings.BIOMETRIC_ALLOW_SIMULATOR = False
    settings.BIOMETRIC_KEYS = {}
    assert {e.id for e in biometric_deployment_checks(None)} == {"biometrics.E002", "biometrics.E003"}


def test_chave_invalida_e_nonce_corrompido_falham_fechados(settings):
    settings.BIOMETRIC_KEYS = {"bad": "***"}
    with pytest.raises(crypto.CryptoUnavailable):
        crypto.decrypt("bad", b"0" * 12, b"ciphertext", b"aad")
    settings.BIOMETRIC_KEYS = {"test": b64(b"0" * 32)}
    with pytest.raises(crypto.DecryptionFailed):
        crypto.decrypt("test", b"", b"ciphertext", b"aad")


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("method", ["face", "authorized_exception"])
def test_token_concorrente_postgresql(tenant_a, method):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import close_old_connections, connection

    from apps.timeclock.services import IdentificationRejected, record_punch

    if connection.vendor != "postgresql":
        pytest.skip("Concorrência exige PostgreSQL real")
    unit = make_unit(tenant_a.company)
    device, token = make_device(tenant_a.company, unit)
    employee = make_employee(tenant_a.company, unit)
    if method == "face":
        enroll_via_api(tenant_a, employee)
        verified = verify(tablet(token)).json()
        identification = {
            "method": method,
            "verification_id": verified["verification_id"],
            "verification_token": verified["verification_token"],
        }
    else:
        _, code = services.create_exception(
            company=tenant_a.company,
            employee=employee,
            user=tenant_a.users["company_admin"],
            reason="Câmera quebrada",
        )
        identification = {"method": method, "code": code}
    barrier = Barrier(2)

    def run():
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            record_punch(
                device=device, registration="1", client_event_id=uuid.uuid4(), identification=identification
            )
            return True
        except IdentificationRejected:
            return False
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(run) for _ in range(2)]
        assert sorted(job.result(timeout=20) for job in jobs) == [False, True]
    assert TimeRecord.objects.count() == 1


@pytest.mark.parametrize("token", [None, "", "forged", [], True])
def test_id_sequencial_nao_substitui_token_assinado(world, token):
    tenant, _, _, client, employee = world
    enroll_via_api(tenant, employee)
    vid = verify(client).json()["verification_id"]
    assert punch(client, method="face", verification_id=vid, verification_token=token).status_code == 400
    assert not TimeRecord.objects.exists()
    assert VerificationAttempt.objects.get(pk=vid).consumed_at is None
    assert punch(client, method="face", verification_id=vid).status_code == 201


def test_consentimento_verificado_antes_de_processar_imagens(world):
    tenant, _, _, _, employee = world
    with mock.patch.object(engines.SimulatorEngine, "enroll") as engine:
        response = tenant.client("company_admin").post(
            url(tenant.company, employee, "biometric/enroll/"), {"images": [b64(JPEG)]}, format="json"
        )
    assert response.status_code == 400
    engine.assert_not_called()


@pytest.mark.parametrize("method", [[], {}, True, 1, "inexistente"])
def test_modo_facial_nao_aceita_metodo_inesperado(world, method):
    tenant, _, _, client, _ = world
    tenant.company.identification_mode = "face"
    tenant.company.save()
    assert punch(client, method=method).status_code == 400
    assert not TimeRecord.objects.exists()


@pytest.mark.parametrize("reason", [[], {}, True, 1, None])
def test_excecao_motivo_de_tipo_inesperado(world, reason):
    tenant, _, _, _, employee = world
    assert (
        tenant.client("company_admin")
        .post(exception_url(tenant.company, employee), {"reason": reason}, format="json")
        .status_code
        == 400
    )


def test_nao_verifica_template_de_outro_motor(world):
    tenant, _, _, client, employee = world
    enroll_via_api(tenant, employee)
    BiometricTemplate.objects.update(engine_version="incompativel")
    with mock.patch.object(engines.SimulatorEngine, "verify") as engine:
        assert verify(client).status_code == 503
    engine.assert_not_called()


@pytest.mark.django_db(transaction=True)
def test_falhas_concorrentes_respeitam_bloqueio_postgresql(tenant_a):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import connection

    if connection.vendor != "postgresql":
        pytest.skip("Concorrência exige PostgreSQL real")
    unit = make_unit(tenant_a.company)
    device, _ = make_device(tenant_a.company, unit)
    employee = make_employee(tenant_a.company, unit)
    enroll_via_api(tenant_a, employee)
    for _ in range(4):
        services.verify_face(device=device, employee=employee, image=OUTRA)
    barrier = Barrier(2)

    def run():
        try:
            barrier.wait(timeout=10)
            return services.verify_face(device=device, employee=employee, image=OUTRA).outcome
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(run) for _ in range(2)]
        assert sorted(job.result(timeout=20) for job in jobs) == ["locked", "no_match"]


# ---------- Ordem de bloqueios (PostgreSQL) ----------


@pytest.mark.skipif(connection.vendor != "postgresql", reason="Bloqueios de linha exigem PostgreSQL real")
@pytest.mark.django_db(transaction=True)
def test_verificacao_e_marcacao_concorrentes_nao_geram_deadlock(world):
    """Regressão: a verificação segura o funcionário e insere a tentativa (a FK pede lock no dispositivo);
    a marcação segura o dispositivo e pede o funcionário. Com FOR UPDATE nos dois, o ciclo fecha."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import close_old_connections

    from apps.operations import services as ops_services
    from apps.timeclock import services as timeclock

    tenant, _, device, _, employee = world
    admin = tenant.users["company_admin"]
    services.grant_consent(employee=employee, user=admin, policy_version="v1")
    services.enroll(employee=employee, user=admin, images_b64=[b64(JPEG)])
    barrier = Barrier(2)
    real_attempt = services._attempt
    real_lookup = ops_services.employee_for_device

    def attempt_after_barrier(*args, **kwargs):
        barrier.wait(timeout=10)  # a verificação já segura o funcionário
        return real_attempt(*args, **kwargs)

    def lookup_after_barrier(*args, **kwargs):
        barrier.wait(timeout=10)  # a marcação já segura o dispositivo
        return real_lookup(*args, **kwargs)

    def run_verify():
        close_old_connections()
        try:
            return services.verify_face(device=device, employee=employee, image=JPEG).outcome
        finally:
            close_old_connections()

    def run_punch():
        close_old_connections()
        try:
            record, created = timeclock.record_punch(
                device=device, registration="1", client_event_id=uuid.uuid4()
            )
            return created
        finally:
            close_old_connections()

    with (
        mock.patch.object(services, "_attempt", attempt_after_barrier),
        mock.patch.object(ops_services, "employee_for_device", lookup_after_barrier),
    ):
        with ThreadPoolExecutor(max_workers=2) as pool:
            verify_future, punch_future = pool.submit(run_verify), pool.submit(run_punch)
            assert verify_future.result(timeout=30) == "success"
            assert punch_future.result(timeout=30) is True
    assert TimeRecord.objects.count() == 1


# ---------- Cota de tentativas por exceção ----------


def _punch_exception(client, registration, code):
    body = {
        "registration": registration,
        "client_event_id": str(uuid.uuid4()),
        "identification": {"method": "authorized_exception", "code": code},
    }
    return client.post("/api/device/punches/", body, format="json")


def _new_exception_code(tenant, employee):
    return (
        tenant.client("company_admin")
        .post(exception_url(tenant.company, employee), {"reason": "Câmera danificada"}, format="json")
        .json()["code"]
    )


def test_marcacoes_validas_por_excecao_nao_esgotam_a_cota(world):
    """Regressão (revisão da etapa 6): 12 funcionários diferentes, mesmo aparelho, mesmo minuto."""
    from apps.biometrics.models import ExceptionBudget

    tenant, unit, device, client, _ = world
    employees = [make_employee(tenant.company, unit, str(100 + i), f"Pessoa {i}") for i in range(12)]
    for employee in employees:
        code = _new_exception_code(tenant, employee)
        assert _punch_exception(client, employee.registration, code).status_code == 201
    assert TimeRecord.objects.count() == 12
    # nada sobrou na cota: só falhas contam
    assert ExceptionBudget.objects.get(scope=f"device:{device.pk}").count == 0


def test_adivinhacao_de_codigo_continua_limitada_e_nao_e_devolvida(world):
    from apps.biometrics.models import ExceptionBudget

    tenant, unit, device, client, employee = world
    valid = _new_exception_code(tenant, employee)
    wrong = f"{(int(valid) + 1) % 10**8:08d}"
    results = [_punch_exception(client, employee.registration, wrong).status_code for _ in range(12)]
    assert results[:10] == [400] * 10 and 429 in results[10:]
    assert ExceptionBudget.objects.get(scope=f"device:{device.pk}").count == 10
    # com a cota esgotada, até o código correto é recusado antes de ser avaliado
    assert _punch_exception(client, employee.registration, valid).status_code == 429
    assert TimeRecord.objects.count() == 0


def test_sucesso_devolve_so_a_propria_tentativa_e_erro_interno_nao_devolve(world):
    from apps.biometrics.models import ExceptionBudget

    tenant, unit, device, client, employee = world
    valid = _new_exception_code(tenant, employee)
    wrong = f"{(int(valid) + 1) % 10**8:08d}"
    for _ in range(3):
        assert _punch_exception(client, employee.registration, wrong).status_code == 400
    assert _punch_exception(client, employee.registration, valid).status_code == 201
    assert ExceptionBudget.objects.get(scope=f"device:{device.pk}").count == 3  # as 3 falhas seguem contadas
    # erro interno após reservar: a tentativa não é devolvida (sem sucesso gravado)
    again = _new_exception_code(tenant, employee)
    with mock.patch("apps.timeclock.services._insert", side_effect=RuntimeError("disco cheio")):
        # rota sensível: o middleware devolve 500 genérico (sem vazar a exceção)
        assert _punch_exception(client, employee.registration, again).status_code == 500
    assert ExceptionBudget.objects.get(scope=f"device:{device.pk}").count == 4


# ---------- Contrato usado pelo tablet para retomar tentativas sem confirmação ----------


def test_evento_gravado_e_devolvido_antes_de_validar_identificacao_ou_matricula(world):
    """O Dart conclui que 400/404 no reenvio prova que o evento NÃO foi gravado, porque o servidor
    consulta o evento existente antes de validar matrícula, identificação ou política."""
    tenant, _, _, client, employee = world
    event = str(uuid.uuid4())
    first = client.post(
        "/api/device/punches/", {"registration": "1", "client_event_id": event}, format="json"
    )
    assert first.status_code == 201
    tenant.company.identification_mode = "face"  # a política passou a exigir face depois da gravação
    tenant.company.save()
    variations = [
        {"registration": "999"},  # matrícula inexistente
        {"identification": {"method": "authorized_exception", "code": "00000000"}},  # código inválido
        {"identification": {"method": "face", "verification_id": 987654, "verification_token": "x"}},
        {"identification": {"method": "registration"}},  # método agora proibido pela política
    ]
    for extra in variations:
        body = {"registration": "1", "client_event_id": event, **extra}
        again = client.post("/api/device/punches/", body, format="json")
        assert again.status_code == 200 and again.json()["duplicate"] is True, extra
        assert again.json()["record"]["id"] == first.json()["record"]["id"]
    assert TimeRecord.objects.count() == 1


def test_rotacao_de_chave_recifra_templates(world, settings):
    import base64 as b64mod
    import os

    from django.core.management import call_command

    tenant, _, _, client, employee = world
    enroll_via_api(tenant, employee)
    old = BiometricTemplate.objects.get(status="active")
    settings.BIOMETRIC_KEYS = {**settings.BIOMETRIC_KEYS, "k2": b64mod.b64encode(os.urandom(32)).decode()}
    settings.BIOMETRIC_ACTIVE_KEY_ID = "k2"
    call_command("rotate_biometric_key")
    new = BiometricTemplate.objects.get(pk=old.pk)
    assert new.key_id == "k2" and bytes(new.ciphertext) != bytes(old.ciphertext)
    # Continua verificando depois de remover a chave antiga.
    settings.BIOMETRIC_KEYS = {"k2": settings.BIOMETRIC_KEYS["k2"]}
    assert verify(client).json()["outcome"] == "success"
