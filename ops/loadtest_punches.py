"""Teste de carga de marcações concorrentes contra um servidor REAL (HTTP), em banco de TESTE.

Cria uma empresa de carga com N unidades, tablets ativos e funcionários; dispara marcações em paralelo
(com reenvios do mesmo evento para provar idempotência) e confere: sem duplicidade, NSR contínuo e cadeia
íntegra. Uso (em backend/, com DATABASE_URL do banco de teste e o servidor rodando):

    python ../ops/loadtest_punches.py --url http://127.0.0.1:8001 --units 2 --devices 8 --punches 2000 --threads 32
"""

import argparse
import datetime
import os
import statistics
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import django

sys.path.insert(0, os.getcwd())
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import json  # noqa: E402
import urllib.request  # noqa: E402

from apps.companies.models import Company  # noqa: E402
from apps.devices import services as device_services  # noqa: E402
from apps.devices.models import Device  # noqa: E402
from apps.operations import services as ops  # noqa: E402
from apps.operations.models import Employee, Unit  # noqa: E402
from apps.timeclock.models import TimeRecord  # noqa: E402
from apps.timeclock.services import verify_unit_chain  # noqa: E402


def setup(units, devices, employees_per_unit):
    company = Company.objects.create(name=f"Carga {uuid.uuid4().hex[:6]}")
    tokens = []
    for u in range(units):
        unit = Unit.objects.create(company=company, name=f"Unidade {u}")
        regs = []
        for i in range(employees_per_unit):
            e = Employee.objects.create(company=company, registration=f"{u}-{i}", full_name=f"Pessoa {u}-{i}")
            ops.assign_unit(e, company, unit, None, datetime.date(2020, 1, 1))
            regs.append(e.registration)
        for d in range(devices // units):
            device = Device.objects.create(company=company, unit=unit, name=f"T{u}-{d}")
            code, _ = device_services.new_activation_code(device)
            _, token = device_services.activate(code)
            tokens.append((token, regs))
    return company, tokens


def post(url, token, body):
    req = urllib.request.Request(
        url + "/api/device/punches/",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Device {token}"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
            status = r.status
    except urllib.error.HTTPError as e:
        status = e.code
    return status, (time.perf_counter() - started) * 1000


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://127.0.0.1:8001")
    p.add_argument("--units", type=int, default=2)
    p.add_argument("--devices", type=int, default=8)
    p.add_argument("--employees", type=int, default=50)
    p.add_argument("--punches", type=int, default=1000)
    p.add_argument("--threads", type=int, default=32)
    p.add_argument("--resend-every", type=int, default=10, help="reenvia o mesmo evento a cada N")
    a = p.parse_args()

    company, devices = setup(a.units, a.devices, a.employees)

    jobs = []
    for i in range(a.punches):
        token, regs = devices[i % len(devices)]
        event = str(uuid.uuid4())
        jobs.append((token, {"registration": regs[i % len(regs)], "client_event_id": event}))
        if a.resend_every and i % a.resend_every == 0:
            jobs.append((token, {"registration": regs[i % len(regs)], "client_event_id": event}))

    started = time.perf_counter()
    with ThreadPoolExecutor(a.threads) as pool:
        results = list(pool.map(lambda j: post(a.url, *j), jobs))
    elapsed = time.perf_counter() - started
    lat = sorted(ms for _, ms in results)
    statuses = {}
    for s, _ in results:
        statuses[s] = statuses.get(s, 0) + 1
    records = TimeRecord.objects.filter(company=company)
    problems = [p for u in Unit.objects.filter(company=company) for p in verify_unit_chain(u)]
    print(json.dumps({
        "requests": len(jobs),
        "unique_events": a.punches,
        "records": records.count(),
        "statuses": statuses,
        "seconds": round(elapsed, 2),
        "req_per_s": round(len(jobs) / elapsed, 1),
        "p50_ms": round(statistics.median(lat), 1),
        "p95_ms": round(lat[int(len(lat) * 0.95) - 1], 1),
        "p99_ms": round(lat[int(len(lat) * 0.99) - 1], 1),
        "chain_problems": problems[:5],
    }, ensure_ascii=False, indent=2))
    ok = records.count() == a.punches and not problems and set(statuses) <= {200, 201}
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
