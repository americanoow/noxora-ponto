"""Gateways de pagamento. Hoje só existe o SANDBOX local: não movimenta dinheiro nem chama terceiros.

Um gateway real (Asaas, Stripe, Pagar.me, Iugu…) é um adaptador desta interface e depende de contrato e
credenciais: decisão do responsável pelo produto. O sandbox produz eventos assinados por HMAC no mesmo
formato que o endpoint de webhook valida, para testar o ciclo completo.
"""

import hashlib
import hmac
import json
import secrets

from django.conf import settings


class GatewayError(Exception):
    pass


class SandboxGateway:
    name = "sandbox"
    is_sandbox = True

    def create_customer(self, company) -> str:
        return f"sbx_cus_{secrets.token_hex(8)}"

    def create_invoice(self, invoice) -> tuple[str, str]:
        invoice_id = f"sbx_inv_{secrets.token_hex(10)}"
        return invoice_id, f"{settings.FRONTEND_URL}/cobranca/sandbox/{invoice_id}"

    # ---- simulação do lado do gateway ----

    @staticmethod
    def sign(body: bytes) -> str:
        return (
            "sha256=" + hmac.new(settings.BILLING_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
        )

    def simulate_event(self, event_type: str, invoice_id: str) -> tuple[bytes, str]:
        body = json.dumps(
            {"id": f"sbx_evt_{secrets.token_hex(10)}", "type": event_type, "data": {"invoice_id": invoice_id}}
        ).encode()
        return body, self.sign(body)


GATEWAYS = {"sandbox": SandboxGateway}


def get_gateway():
    cls = GATEWAYS.get(settings.BILLING_GATEWAY)
    if cls is None:
        raise GatewayError("Gateway de pagamento não configurado.")
    return cls()


def verify_signature(body: bytes, header: str) -> bool:
    if not settings.BILLING_WEBHOOK_SECRET or not header:
        return False
    expected = (
        "sha256=" + hmac.new(settings.BILLING_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    )
    return hmac.compare_digest(expected, header)
