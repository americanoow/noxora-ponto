import base64
import datetime
import uuid
from unittest import mock

import pytest
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.biometrics import crypto, engines, services
from apps.biometrics.models import (
    BiometricConsent,
    BiometricTemplate,
    ExceptionAuthorization,
    Outcome,
    VerificationAttempt,
)
from apps.devices import services as device_services
from apps.devices.models import Device
from apps.operations import services as ops
from apps.operations.models import Employee, Unit
from apps.timeclock.models import TimeRecord

pytestmark = pytest.mark.django_db

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
    return client.post(
        "/api/device/face/verify/", {"registration": registration, "image": b64(image)}, format="json"
    )


def punch(client, **identification):
    body = {"registration": "1", "client_event_id": str(uuid.uuid4())}
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
        "identification": {"method": "face", "verification_id": vid3},
    }
    assert client.post("/api/device/punches/", other_body, format="json").status_code == 400
    # de outro dispositivo
    _, token2 = make_device(tenant.company, unit, "Outro")
    assert punch(tablet(token2), method="face", verification_id=vid3).status_code == 400
    assert TimeRecord.objects.count() == 1
    # tipos inválidos e ids inexistentes
    for bad in (None, True, "1", 10**9, [1], {"a": 1}):
        assert punch(client, method="face", verification_id=bad).status_code == 400


def test_falha_na_marcacao_nao_consome_a_verificacao(world):
    tenant, _, _, client, employee = world
    enroll_via_api(tenant, employee)
    vid = verify(client).json()["verification_id"]
    with mock.patch("apps.timeclock.services._insert", side_effect=RuntimeError("disco cheio")):
        with pytest.raises(RuntimeError):
            punch(client, method="face", verification_id=vid)
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
        "identification": {"method": "face", "verification_id": vid},
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
        name = "sem-vivacidade"
        is_simulator = False

        def verify(self, template, probe):
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
    assert tenant_a.client("manager").get(path).json() == {"mode": "registration"}
    assert tenant_a.client("employee").get(path).status_code == 403
    assert tenant_a.client("manager").patch(path, {"mode": "face"}, format="json").status_code == 403
    for bad in ({"mode": "x"}, {}, {"mode": None}):
        assert tenant_a.client("company_admin").patch(path, bad, format="json").status_code == 400
    assert tenant_a.client("company_admin").patch(path, {"mode": "face"}, format="json").json() == {
        "mode": "face"
    }
    log = AuditLog.objects.get(action="identification.mode_changed")
    assert log.metadata["before"] == "registration" and log.metadata["after"] == "face"
    assert (
        tenant_b.client("company_admin").patch(path, {"mode": "registration"}, format="json").status_code
        == 404
    )


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
