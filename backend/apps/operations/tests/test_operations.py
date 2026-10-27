import datetime

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.operations import services
from apps.operations.models import Employee, Sector, Unit

pytestmark = pytest.mark.django_db

CPF_OK = "529.982.247-25"
CPF_OK_2 = "111.444.777-35"


def url(company, path):
    return f"/api/companies/{company.pk}/{path}"


def make_unit(company, name="Centro"):
    return Unit.objects.create(company=company, name=name)


def make_sector(unit, name="Atendimento"):
    return Sector.objects.create(company=unit.company, unit=unit, name=name)


def make_employee(company, registration, name="Fulano", unit=None, sector=None, start=None):
    employee = Employee.objects.create(company=company, registration=registration, full_name=name)
    if unit:
        services.assign_unit(employee, company, unit, sector, start or datetime.date(2020, 1, 1))
    return employee


# ---------- CPF ----------


def test_cpf_valido_e_invalido():
    assert services.validate_cpf(CPF_OK) == "52998224725"
    assert services.validate_cpf("") == ""
    for bad in ("111.111.111-11", "529.982.247-24", "123", "abc"):
        with pytest.raises(ValueError):
            services.validate_cpf(bad)
    assert services.mask_cpf("52998224725") == "***.***.***-25"


# ---------- Unidades e setores ----------


def test_admin_cria_unidade_e_nome_duplicado_e_rejeitado_sem_distinguir_caixa(tenant_a):
    admin = tenant_a.client("company_admin")
    assert admin.post(url(tenant_a.company, "units/"), {"name": "Centro"}, format="json").status_code == 201
    assert admin.post(url(tenant_a.company, "units/"), {"name": "CENTRO"}, format="json").status_code == 400
    r = admin.post(
        url(tenant_a.company, "units/"), {"name": "Norte", "timezone": "Marte/Base"}, format="json"
    )
    assert r.status_code == 400


def test_mesmo_nome_de_unidade_em_empresas_diferentes_e_permitido(tenant_a, tenant_b):
    make_unit(tenant_a.company, "Centro")
    r = tenant_b.client("company_admin").post(
        url(tenant_b.company, "units/"), {"name": "Centro"}, format="json"
    )
    assert r.status_code == 201


def test_funcionario_nao_acessa_cadastros(tenant_a):
    client = tenant_a.client("employee")
    for path in ("units/", "sectors/", "employees/", "schedules/"):
        assert client.get(url(tenant_a.company, path)).status_code == 403


def test_gestor_nao_escreve_cadastros(tenant_a):
    manager = tenant_a.client("manager")
    assert manager.post(url(tenant_a.company, "units/"), {"name": "X"}, format="json").status_code == 403
    assert (
        manager.post(
            url(tenant_a.company, "employees/"), {"registration": "1", "full_name": "A"}, format="json"
        ).status_code
        == 403
    )
    assert (
        manager.post(
            url(tenant_a.company, "employees/import/"), {"csv": "matricula,nome\n1,A"}, format="json"
        ).status_code
        == 403
    )


def test_setor_com_unidade_de_outra_empresa_e_rejeitado(tenant_a, tenant_b):
    unit_b = make_unit(tenant_b.company)
    r = tenant_a.client("company_admin").post(
        url(tenant_a.company, "sectors/"), {"name": "Vendas", "unit": unit_b.pk}, format="json"
    )
    assert r.status_code == 400
    assert not Sector.objects.exists()


def test_unidade_do_setor_nao_muda(tenant_a):
    u1, u2 = make_unit(tenant_a.company, "A"), make_unit(tenant_a.company, "B")
    sector = make_sector(u1)
    tenant_a.client("company_admin").patch(
        url(tenant_a.company, f"sectors/{sector.pk}/"), {"unit": u2.pk, "name": "Novo"}, format="json"
    )
    sector.refresh_from_db()
    assert sector.unit_id == u1.pk and sector.name == "Novo"


def test_cadastros_de_outra_empresa_sao_invisiveis(tenant_a, tenant_b):
    unit_b = make_unit(tenant_b.company)
    sector_b = make_sector(unit_b)
    emp_b = make_employee(tenant_b.company, "9", unit=unit_b)
    admin = tenant_a.client("company_admin")
    assert admin.get(url(tenant_a.company, f"units/{unit_b.pk}/")).status_code == 404
    assert (
        admin.patch(url(tenant_a.company, f"units/{unit_b.pk}/"), {"name": "x"}, format="json").status_code
        == 404
    )
    assert (
        admin.patch(
            url(tenant_a.company, f"sectors/{sector_b.pk}/"), {"name": "x"}, format="json"
        ).status_code
        == 404
    )
    assert admin.get(url(tenant_a.company, f"employees/{emp_b.pk}/")).status_code == 404
    assert (
        admin.patch(
            url(tenant_a.company, f"employees/{emp_b.pk}/"), {"full_name": "x"}, format="json"
        ).status_code
        == 404
    )
    assert admin.get(url(tenant_a.company, f"employees/{emp_b.pk}/assignments/")).status_code == 404
    assert admin.get(url(tenant_a.company, "employees/")).json()["count"] == 0
    # pela URL da empresa B o administrador de A também não passa
    assert admin.get(url(tenant_b.company, f"employees/{emp_b.pk}/")).status_code == 404


# ---------- Funcionários ----------


def test_cria_funcionario_com_cpf_mascarado_na_listagem(tenant_a):
    admin = tenant_a.client("company_admin")
    r = admin.post(
        url(tenant_a.company, "employees/"),
        {"registration": " 001 ", "full_name": " Maria ", "cpf": CPF_OK},
        format="json",
    )
    assert r.status_code == 201
    assert r.json()["cpf"] == "52998224725"
    listed = admin.get(url(tenant_a.company, "employees/")).json()["results"][0]
    assert (
        listed["cpf"] == "***.***.***-25"
        and listed["registration"] == "001"
        and listed["full_name"] == "Maria"
    )


def test_matricula_cpf_duplicados_e_invalidos(tenant_a, tenant_b):
    admin = tenant_a.client("company_admin")
    base = {"registration": "1", "full_name": "A", "cpf": CPF_OK}
    assert admin.post(url(tenant_a.company, "employees/"), base, format="json").status_code == 201
    assert (
        admin.post(url(tenant_a.company, "employees/"), {**base, "cpf": ""}, format="json").status_code == 400
    )
    assert (
        admin.post(
            url(tenant_a.company, "employees/"), {**base, "registration": "2"}, format="json"
        ).status_code
        == 400
    )
    assert (
        admin.post(
            url(tenant_a.company, "employees/"),
            {"registration": "3", "full_name": "B", "cpf": "123"},
            format="json",
        ).status_code
        == 400
    )
    # a mesma matrícula/CPF em outra empresa é permitido
    assert (
        tenant_b.client("company_admin")
        .post(url(tenant_b.company, "employees/"), base, format="json")
        .status_code
        == 201
    )


def test_patch_ignora_matricula_e_campos_extras_e_inativacao_preserva_historico(tenant_a):
    unit = make_unit(tenant_a.company)
    emp = make_employee(tenant_a.company, "10", unit=unit)
    admin = tenant_a.client("company_admin")
    r = admin.patch(
        url(tenant_a.company, f"employees/{emp.pk}/"),
        {"registration": "999", "company": 12345, "full_name": "Novo Nome", "is_active": False},
        format="json",
    )
    assert r.status_code == 200
    emp.refresh_from_db()
    assert emp.registration == "10" and emp.company_id == tenant_a.company.pk
    assert emp.full_name == "Novo Nome" and emp.is_active is False and emp.inactivated_at is not None
    assert emp.assignments.count() == 1
    admin.patch(url(tenant_a.company, f"employees/{emp.pk}/"), {"is_active": True}, format="json")
    emp.refresh_from_db()
    assert emp.is_active and emp.inactivated_at is None


def test_acesso_do_funcionario_exige_vinculo_na_propria_empresa(tenant_a, tenant_b):
    admin = tenant_a.client("company_admin")
    emp = make_employee(tenant_a.company, "1")
    path = url(tenant_a.company, f"employees/{emp.pk}/")
    assert (
        admin.patch(path, {"access_email": tenant_b.users["employee"].email}, format="json").status_code
        == 400
    )
    ok = admin.patch(path, {"access_email": tenant_a.users["employee"].email}, format="json")
    assert ok.status_code == 200 and ok.json()["access_email"] == tenant_a.users["employee"].email


def test_listagem_busca_filtros_e_paginacao(tenant_a):
    u1, u2 = make_unit(tenant_a.company, "Centro"), make_unit(tenant_a.company, "Norte")
    s1 = make_sector(u1, "Estoque")
    for i in range(30):
        make_employee(
            tenant_a.company,
            f"{i:03d}",
            f"Pessoa {i:02d}",
            unit=u1 if i < 20 else u2,
            sector=s1 if i < 5 else None,
        )
    make_employee(tenant_a.company, "999", "Sem Lotação")
    admin = tenant_a.client("company_admin")
    base = url(tenant_a.company, "employees/")
    first = admin.get(base).json()
    assert first["count"] == 31 and len(first["results"]) == 25 and first["next"]
    assert len(admin.get(base + "?page=2").json()["results"]) == 6
    assert admin.get(base + "?page_size=1000").json()["results"].__len__() == 31  # limitado a 100
    assert admin.get(base + f"?unit={u1.pk}").json()["count"] == 20
    assert admin.get(base + f"?sector={s1.pk}").json()["count"] == 5
    assert admin.get(base + "?q=Pessoa 07").json()["count"] == 1
    assert admin.get(base + "?q=999").json()["count"] == 1
    assert admin.get(base + "?unit=abc").json()["count"] == 0
    Employee.objects.filter(registration="000").update(is_active=False)
    assert admin.get(base + "?active=false").json()["count"] == 1


# ---------- Escopo do gestor ----------


def test_gestor_sem_escopo_nao_ve_funcionarios_e_com_escopo_ve_so_o_seu(tenant_a):
    u1, u2 = make_unit(tenant_a.company, "Centro"), make_unit(tenant_a.company, "Norte")
    e1 = make_employee(tenant_a.company, "1", unit=u1)
    e2 = make_employee(tenant_a.company, "2", unit=u2)
    make_employee(tenant_a.company, "3")  # sem lotação
    manager = tenant_a.client("manager")
    base = url(tenant_a.company, "employees/")
    assert manager.get(base).json()["count"] == 0
    admin = tenant_a.client("company_admin")
    member = tenant_a.memberships["manager"]
    r = admin.patch(
        url(tenant_a.company, f"members/{member.pk}/"), {"scope_unit_ids": [u1.pk]}, format="json"
    )
    assert r.status_code == 200 and r.json()["scope_unit_ids"] == [u1.pk]
    assert [e["id"] for e in manager.get(base).json()["results"]] == [e1.pk]
    assert manager.get(base + f"{e2.pk}/").status_code == 404
    assert manager.get(base + f"{e2.pk}/assignments/").status_code == 404
    assert [u["id"] for u in manager.get(url(tenant_a.company, "units/")).json()] == [u1.pk]


def test_escopo_por_setor(tenant_a):
    u = make_unit(tenant_a.company)
    s1, s2 = make_sector(u, "A"), make_sector(u, "B")
    e1 = make_employee(tenant_a.company, "1", unit=u, sector=s1)
    make_employee(tenant_a.company, "2", unit=u, sector=s2)
    tenant_a.client("company_admin").patch(
        url(tenant_a.company, f"members/{tenant_a.memberships['manager'].pk}/"),
        {"scope_sector_ids": [s1.pk]},
        format="json",
    )
    ids = [
        e["id"] for e in tenant_a.client("manager").get(url(tenant_a.company, "employees/")).json()["results"]
    ]
    assert ids == [e1.pk]


def test_escopo_com_unidade_de_outra_empresa_e_rejeitado(tenant_a, tenant_b):
    unit_b = make_unit(tenant_b.company)
    r = tenant_a.client("company_admin").patch(
        url(tenant_a.company, f"members/{tenant_a.memberships['manager'].pk}/"),
        {"scope_unit_ids": [unit_b.pk]},
        format="json",
    )
    assert r.status_code == 400
    assert tenant_a.memberships["manager"].scope_units.count() == 0


def test_gestor_ve_cpf_mascarado_no_detalhe(tenant_a):
    u = make_unit(tenant_a.company)
    emp = make_employee(tenant_a.company, "1", unit=u)
    Employee.objects.filter(pk=emp.pk).update(cpf="52998224725")
    tenant_a.memberships["manager"].scope_units.add(u)
    body = tenant_a.client("manager").get(url(tenant_a.company, f"employees/{emp.pk}/")).json()
    assert body["cpf"] == "***.***.***-25"
    assert (
        tenant_a.client("company_admin").get(url(tenant_a.company, f"employees/{emp.pk}/")).json()["cpf"]
        == "52998224725"
    )


# ---------- Lotação com vigência ----------


def test_mudanca_de_lotacao_preserva_o_historico(tenant_a):
    u1, u2 = make_unit(tenant_a.company, "Centro"), make_unit(tenant_a.company, "Norte")
    emp = make_employee(tenant_a.company, "1", unit=u1, start=datetime.date(2024, 1, 1))
    admin = tenant_a.client("company_admin")
    r = admin.post(
        url(tenant_a.company, f"employees/{emp.pk}/assignments/"),
        {"unit": u2.pk, "valid_from": "2025-03-01"},
        format="json",
    )
    assert r.status_code == 201
    rows = list(emp.assignments.order_by("valid_from"))
    assert [(a.unit_id, a.valid_from, a.valid_to) for a in rows] == [
        (u1.pk, datetime.date(2024, 1, 1), datetime.date(2025, 2, 28)),
        (u2.pk, datetime.date(2025, 3, 1), None),
    ]
    listed = admin.get(url(tenant_a.company, f"employees/{emp.pk}/assignments/")).json()
    assert [a["unit"]["name"] for a in listed] == ["Norte", "Centro"]  # mais recente primeiro
    assert admin.get(url(tenant_a.company, f"employees/{emp.pk}/")).json()["unit"]["name"] == "Norte"


def test_lotacao_retroativa_ou_mesma_data_e_rejeitada(tenant_a):
    u1, u2 = make_unit(tenant_a.company, "Centro"), make_unit(tenant_a.company, "Norte")
    emp = make_employee(tenant_a.company, "1", unit=u1, start=datetime.date(2024, 1, 1))
    admin = tenant_a.client("company_admin")
    path = url(tenant_a.company, f"employees/{emp.pk}/assignments/")
    for date in ("2024-01-01", "2023-06-01"):
        assert admin.post(path, {"unit": u2.pk, "valid_from": date}, format="json").status_code == 400
    assert emp.assignments.count() == 1 and emp.assignments.get().valid_to is None


def test_lotacao_valida_unidade_e_setor(tenant_a, tenant_b):
    u1, u2 = make_unit(tenant_a.company, "Centro"), make_unit(tenant_a.company, "Norte")
    sector_u2 = make_sector(u2)
    unit_b = make_unit(tenant_b.company)
    emp = make_employee(tenant_a.company, "1")
    admin = tenant_a.client("company_admin")
    path = url(tenant_a.company, f"employees/{emp.pk}/assignments/")
    assert admin.post(path, {"unit": unit_b.pk, "valid_from": "2025-01-01"}, format="json").status_code == 400
    assert (
        admin.post(
            path, {"unit": u1.pk, "sector": sector_u2.pk, "valid_from": "2025-01-01"}, format="json"
        ).status_code
        == 400
    )
    u2.is_active = False
    u2.save()
    assert admin.post(path, {"unit": u2.pk, "valid_from": "2025-01-01"}, format="json").status_code == 400
    assert emp.assignments.count() == 0


def test_mudanca_futura_nao_altera_a_lotacao_atual(tenant_a):
    u1, u2 = make_unit(tenant_a.company, "Centro"), make_unit(tenant_a.company, "Norte")
    emp = make_employee(tenant_a.company, "1", unit=u1, start=datetime.date(2020, 1, 1))
    future = timezone.localdate() + datetime.timedelta(days=30)
    services.assign_unit(emp, tenant_a.company, u2, None, future)
    emp = Employee.objects.prefetch_related("assignments").get(pk=emp.pk)
    assert services.current_assignment(emp).unit_id == u1.pk


# ---------- Jornadas ----------

DAYS = [{"weekday": d, "start_time": "08:00", "end_time": "17:00", "break_minutes": 60} for d in range(5)]


def test_cria_jornada_e_atribui_com_vigencia(tenant_a):
    admin = tenant_a.client("company_admin")
    r = admin.post(url(tenant_a.company, "schedules/"), {"name": "Comercial", "days": DAYS}, format="json")
    assert r.status_code == 201 and len(r.json()["days"]) == 5
    emp = make_employee(tenant_a.company, "1")
    sid = r.json()["id"]
    path = url(tenant_a.company, f"employees/{emp.pk}/schedules/")
    assert admin.post(path, {"schedule": sid, "valid_from": "2025-01-01"}, format="json").status_code == 201
    assert admin.post(path, {"schedule": sid, "valid_from": "2024-01-01"}, format="json").status_code == 400
    assert len(admin.get(path).json()) == 1


def test_jornada_atribuida_nao_pode_ter_dias_alterados(tenant_a):
    admin = tenant_a.client("company_admin")
    sid = admin.post(
        url(tenant_a.company, "schedules/"), {"name": "Comercial", "days": DAYS}, format="json"
    ).json()["id"]
    emp = make_employee(tenant_a.company, "1")
    admin.post(
        url(tenant_a.company, f"employees/{emp.pk}/schedules/"),
        {"schedule": sid, "valid_from": "2025-01-01"},
        format="json",
    )
    r = admin.patch(url(tenant_a.company, f"schedules/{sid}/"), {"days": DAYS[:2]}, format="json")
    assert r.status_code == 400
    assert len(admin.get(url(tenant_a.company, f"schedules/{sid}/")).json()["days"]) == 5
    assert (
        admin.patch(
            url(tenant_a.company, f"schedules/{sid}/"), {"name": "Renomeada"}, format="json"
        ).status_code
        == 200
    )


def test_jornada_sem_uso_pode_ser_editada_e_noturna_e_aceita(tenant_a):
    admin = tenant_a.client("company_admin")
    night = [{"weekday": 0, "start_time": "22:00", "end_time": "06:00", "break_minutes": 30}]
    sid = admin.post(
        url(tenant_a.company, "schedules/"), {"name": "Noite", "days": night}, format="json"
    ).json()["id"]
    r = admin.patch(url(tenant_a.company, f"schedules/{sid}/"), {"days": DAYS[:1]}, format="json")
    assert r.status_code == 200 and r.json()["days"][0]["start_time"] == "08:00:00"


def test_jornada_invalida(tenant_a):
    admin = tenant_a.client("company_admin")
    path = url(tenant_a.company, "schedules/")
    same = [{"weekday": 0, "start_time": "08:00", "end_time": "08:00", "break_minutes": 0}]
    dup = [DAYS[0], DAYS[0]]
    bad_day = [{**DAYS[0], "weekday": 7}]
    for days in (same, dup, bad_day, []):
        assert admin.post(path, {"name": "X", "days": days}, format="json").status_code == 400
    assert not admin.get(path).json()


def test_jornada_de_outra_empresa_nao_pode_ser_atribuida(tenant_a, tenant_b):
    sid = (
        tenant_b.client("company_admin")
        .post(url(tenant_b.company, "schedules/"), {"name": "B", "days": DAYS}, format="json")
        .json()["id"]
    )
    emp = make_employee(tenant_a.company, "1")
    r = tenant_a.client("company_admin").post(
        url(tenant_a.company, f"employees/{emp.pk}/schedules/"),
        {"schedule": sid, "valid_from": "2025-01-01"},
        format="json",
    )
    assert r.status_code == 400
    assert tenant_a.client("company_admin").get(url(tenant_a.company, f"schedules/{sid}/")).status_code == 404


# ---------- Importação ----------

CSV_OK = (
    "matricula,nome,cpf,unidade,setor,inicio\n"
    "100,Ana,529.982.247-25,Centro,Atendimento,2025-01-10\n"
    "101,Bia,,Centro,,10/02/2025\n"
    "102,Caio,,,,\n"
)


def post_import(client, company, text, commit=False):
    return client.post(url(company, "employees/import/"), {"csv": text, "commit": commit}, format="json")


def test_previa_nao_grava_e_commit_grava_tudo(tenant_a):
    unit = make_unit(tenant_a.company)
    make_sector(unit)
    admin = tenant_a.client("company_admin")
    preview = post_import(admin, tenant_a.company, CSV_OK).json()
    assert preview == {"total": 3, "valid": 3, "errors": [], "committed": 0}
    assert Employee.objects.count() == 0
    done = post_import(admin, tenant_a.company, CSV_OK, commit=True).json()
    assert done["committed"] == 3 and Employee.objects.count() == 3
    ana = Employee.objects.get(registration="100")
    assert ana.cpf == "52998224725" and ana.assignments.get().valid_from == datetime.date(2025, 1, 10)
    assert Employee.objects.get(registration="102").assignments.count() == 0
    assert AuditLog.objects.filter(action="employee.imported", company=tenant_a.company).exists()


def test_erros_na_importacao_tem_linha_e_nada_e_gravado(tenant_a):
    unit = make_unit(tenant_a.company)
    make_sector(unit)
    make_employee(tenant_a.company, "100")
    text = (
        "matricula,nome,cpf,unidade,setor,inicio\n"
        "100,Repetida,,,,\n"  # linha 2: matrícula já cadastrada
        "200,Boa,,Centro,,\n"  # linha 3: ok
        "200,Duplicada,,,,\n"  # linha 4: matrícula repetida no arquivo
        "201,,123,,,\n"  # linha 5: nome vazio e CPF inválido
        "202,Fulano,,Inexistente,,\n"  # linha 6: unidade
        "203,Fulano,,Centro,Nada,\n"  # linha 7: setor
        "204,Fulano,,,Atendimento,\n"  # linha 8: setor sem unidade
        "205,Fulano,,,,31-31-2025\n"  # linha 9: data
    )
    admin = tenant_a.client("company_admin")
    body = post_import(admin, tenant_a.company, text, commit=True).json()
    assert body["committed"] == 0 and body["valid"] == 1 and body["total"] == 8
    found = {(e["line"], e["field"]) for e in body["errors"]}
    assert found == {
        (2, "matricula"),
        (4, "matricula"),
        (5, "nome"),
        (5, "cpf"),
        (6, "unidade"),
        (7, "setor"),
        (8, "setor"),
        (9, "inicio"),
    }
    assert all(e["message"] for e in body["errors"])
    assert Employee.objects.count() == 1


def test_importacao_com_ponto_e_virgula_e_cpf_repetido(tenant_a):
    text = f"matricula;nome;cpf\n1;Ana;{CPF_OK}\n2;Bia;{CPF_OK}\n3;Cia;{CPF_OK_2}\n"
    body = post_import(tenant_a.client("company_admin"), tenant_a.company, text).json()
    assert body["valid"] == 2 and [(e["line"], e["field"]) for e in body["errors"]] == [(3, "cpf")]


@pytest.mark.parametrize(
    "text",
    [
        "nome\nAna\n",
        "matricula,nome,salario\n1,Ana,10\n",
        "matricula,nome\n",
        "",
        "matricula,nome\n" + "1,A\n" * 2001,
    ],
)
def test_arquivo_de_importacao_invalido(tenant_a, text):
    r = post_import(tenant_a.client("company_admin"), tenant_a.company, text)
    assert r.status_code == 400 and "csv" in r.json()


def test_importacao_nao_usa_unidade_de_outra_empresa(tenant_a, tenant_b):
    make_unit(tenant_b.company, "Secreta")
    text = "matricula,nome,unidade\n1,Ana,Secreta\n"
    body = post_import(tenant_a.client("company_admin"), tenant_a.company, text).json()
    assert body["valid"] == 0 and body["errors"][0]["field"] == "unidade"


def test_importacao_com_unidade_inativa_e_rejeitada(tenant_a):
    unit = make_unit(tenant_a.company)
    unit.is_active = False
    unit.save()
    body = post_import(
        tenant_a.client("company_admin"), tenant_a.company, "matricula,nome,unidade\n1,Ana,Centro\n"
    ).json()
    assert body["valid"] == 0


# ---------- Auditoria ----------


def test_auditoria_registra_alteracoes_sem_dados_pessoais(tenant_a):
    admin = tenant_a.client("company_admin")
    admin.post(
        url(tenant_a.company, "employees/"),
        {"registration": "1", "full_name": "Maria Segredo", "cpf": CPF_OK},
        format="json",
    )
    logs = AuditLog.objects.filter(company=tenant_a.company, action="employee.created")
    assert logs.count() == 1
    dump = str(list(AuditLog.objects.values()))
    assert "Segredo" not in dump and "52998224725" not in dump


def test_postgresql_exclusao_de_vigencias_sobrepostas(tenant_a):
    import datetime

    from django.db import IntegrityError, connection, transaction

    from apps.operations.models import Assignment, Employee, Unit

    if connection.vendor != "postgresql":
        pytest.skip("btree_gist só no PostgreSQL")
    unit = Unit.objects.create(company=tenant_a.company, name="U")
    e = Employee.objects.create(company=tenant_a.company, registration="1", full_name="A")
    Assignment.objects.create(employee=e, unit=unit, valid_from=datetime.date(2026, 1, 1))
    with pytest.raises(IntegrityError), transaction.atomic():
        Assignment.objects.create(employee=e, unit=unit, valid_from=datetime.date(2026, 3, 1))
