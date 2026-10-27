"""Teste de fumaça ponta a ponta contra uma implantação (HTTPS), só com a API pública.

Fluxo: plataforma cria empresa → administrador cadastra unidade, jornada e funcionário → tablet é ativado e
marca ponto (online e lote offline) → comprovante → espelho → fechamento → AFD → exportação.
Pré-requisitos: administrador da plataforma (create_platform_admin) e a senha do administrador da
empresa criada (definida pelo convite; aqui por `--set-admin-password-cmd`).

    python ops/smoke_e2e.py --base https://localhost --ca caddy-root.crt --platform-email ... \
        --platform-password ... --set-admin-password-cmd "docker compose ... exec -T backend python manage.py shell -c"
"""

import argparse
import datetime as dt
import http.cookiejar
import json
import shlex
import ssl
import subprocess
import sys
import urllib.request
import uuid


class Client:
    def __init__(self, base, ctx, auth=None):
        self.base, self.ctx, self.auth = base, ctx, auth
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=ctx), urllib.request.HTTPCookieProcessor(self.jar)
        )
        self.csrf = None

    def call(self, method, path, body=None, expect=(200, 201), raw=False):
        headers = {"Content-Type": "application/json", "Referer": self.base + "/"}
        if self.auth:
            headers["Authorization"] = self.auth
        elif method != "GET":
            if self.csrf is None:
                self.csrf = self.call("GET", "/api/auth/csrf/")["csrfToken"]
            headers["X-CSRFToken"] = self.csrf
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with self.opener.open(req, timeout=60) as r:
                status, payload = r.status, r.read()
        except urllib.error.HTTPError as e:
            status, payload = e.code, e.read()
        if status not in expect:
            raise SystemExit(f"FALHA {method} {path}: {status} {payload[:300]!r}")
        if raw:
            return payload
        return json.loads(payload) if payload else None

    def login(self, email, password):
        self.call("POST", "/api/auth/login/", {"email": email, "password": password})
        self.csrf = None  # o token CSRF muda no login


def step(msg):
    print(f"✔ {msg}", flush=True)


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--base", default="https://localhost")
    a.add_argument("--ca")
    a.add_argument("--platform-email", required=True)
    a.add_argument("--platform-password", required=True)
    a.add_argument("--set-admin-password-cmd", required=True)
    args = a.parse_args()
    ctx = ssl.create_default_context(cafile=args.ca) if args.ca else ssl.create_default_context()

    suffix = uuid.uuid4().hex[:6]
    platform = Client(args.base, ctx)
    platform.login(args.platform_email, args.platform_password)
    admin_email = f"admin-{suffix}@smoke.test"
    company = platform.call(
        "POST", "/api/companies/", {"name": f"Smoke {suffix}", "admin_email": admin_email, "admin_name": "Admin"}
    )
    cid = company["id"]
    step(f"empresa criada pela plataforma (id {cid})")

    password = f"Smoke-{uuid.uuid4().hex}"
    code = (
        "from apps.accounts.models import User;"
        f"u=User.objects.get(email='{admin_email}');u.set_password('{password}');u.save()"
    )
    subprocess.run([*shlex.split(args.set_admin_password_cmd), code], check=True)  # noqa: S603
    admin = Client(args.base, ctx)
    admin.login(admin_email, password)
    step("administrador da empresa autenticado")

    base = f"/api/companies/{cid}"
    admin.call("PATCH", f"{base}/employer/", {"legal_name": "Smoke Ltda", "tax_id_type": "CNPJ", "tax_id": "11222333000181"})
    unit = admin.call("POST", f"{base}/units/", {"name": "Matriz", "address": "Rua Teste, 1"})
    schedule = admin.call(
        "POST",
        f"{base}/schedules/",
        {"name": "Comercial", "days": [{"weekday": d, "start_time": "08:00", "end_time": "17:00", "break_minutes": 60} for d in range(5)]},
    )
    employee = admin.call(
        "POST",
        f"{base}/employees/",
        {"registration": "100", "full_name": "Pessoa Smoke", "cpf": "52998224725"},
    )
    start = (dt.date.today() - dt.timedelta(days=3)).isoformat()
    admin.call("POST", f"{base}/employees/{employee['id']}/assignments/", {"unit": unit["id"], "valid_from": start})
    admin.call("POST", f"{base}/employees/{employee['id']}/schedules/", {"schedule": schedule["id"], "valid_from": start})
    admin.call("PATCH", f"{base}/identification/", {"offline_policy": "registration_only"})
    step("unidade, jornada, funcionário e política offline configurados")

    device = admin.call("POST", f"{base}/devices/", {"name": "Tablet Smoke", "unit": unit["id"]})
    activation = device.get("activation_code") or admin.call("POST", f"{base}/devices/{device['id']}/activation-code/")["activation_code"]
    activated = Client(args.base, ctx).call("POST", "/api/device/activate/", {"code": activation})
    tablet = Client(args.base, ctx, auth=f"Device {activated['token']}")
    tablet.call("POST", "/api/device/heartbeat/", {"app_version": "smoke"})
    step("tablet ativado")

    event = str(uuid.uuid4())
    first = tablet.call("POST", "/api/device/punches/", {"registration": "100", "client_event_id": event})
    again = tablet.call("POST", "/api/device/punches/", {"registration": "100", "client_event_id": event})
    assert again["duplicate"] and again["record"]["id"] == first["record"]["id"]
    step(f"marcação online NSR {first['record']['nsr']} e reenvio idempotente")
    now = dt.datetime.now(dt.UTC)
    batch = tablet.call(
        "POST",
        "/api/device/punches/batch/",
        {"events": [{"client_event_id": str(uuid.uuid4()), "registration": "100", "device_reported_at": (now - dt.timedelta(hours=h)).isoformat(), "clock_offset_seconds": 0, "offset_measured_at": now.isoformat()} for h in (3, 2)]},
    )
    assert [r["status"] for r in batch["results"]] == ["confirmed", "confirmed"]
    step("lote offline sincronizado")

    receipt = admin.call("GET", f"{base}/time-records/{first['record']['id']}/receipt.pdf", raw=True)
    assert receipt.startswith(b"%PDF")
    today = dt.date.today().isoformat()
    sheet = admin.call("GET", f"{base}/attendance/timesheet/?employee={employee['id']}&from={start}&to={today}")
    assert sheet["days"] and sheet["totals"] is not None
    step(f"espelho calculado ({len(sheet['days'])} dias, saldo {sheet['totals']['balance_minutes']} min)")
    closing = admin.call("POST", f"{base}/attendance/closings/", {"start": start, "end": today})
    step(f"período fechado (hash {closing['snapshot_sha256'][:12]}…)")
    afd = admin.call("GET", f"{base}/fiscal/afd/?unit={unit['id']}&from={start}&to={today}", raw=True)
    lines = afd.decode("latin-1").split("\r\n")
    assert len(lines[0]) == 302 and len(lines[1]) == 137
    step(f"AFD gerado ({len(lines) - 3} marcações)")
    csv = admin.call("GET", f"{base}/reports/summary.csv?from={start}&to={today}", raw=True)
    assert b"Pessoa Smoke" in csv
    step("resumo CSV exportado")
    print("SMOKE E2E OK")


if __name__ == "__main__":
    sys.exit(main())
