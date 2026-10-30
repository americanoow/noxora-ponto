from rest_framework import serializers

from apps.operations import services as ops_services

from .models import DeclaredKind


class PunchSerializer(serializers.Serializer):
    registration = serializers.CharField(max_length=30)
    client_event_id = serializers.UUIDField()
    declared_kind = serializers.ChoiceField(
        choices=DeclaredKind.choices, required=False, allow_blank=True, default=""
    )
    device_reported_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
    identification = serializers.DictField(required=False, default=None, allow_null=True)
    # Origem do evento: tablet e empresa em que foi feito. Se não conferir com a credencial que o envia
    # (tablet reativado em outra empresa, por exemplo), o evento NUNCA é gravado para outra pessoa.
    origin_device_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    origin_company_id = serializers.IntegerField(required=False, allow_null=True, default=None)

    def validate_registration(self, value):
        return value.strip()

    def validate_identification(self, value):
        if value and not isinstance(value.get("method"), str):
            raise serializers.ValidationError("Informe um método de identificação textual.")
        return value


class OfflineEventSerializer(serializers.Serializer):
    """Evento da fila offline do tablet. O horário é o ORIGINAL do aparelho; o servidor o corrige."""

    client_event_id = serializers.UUIDField()
    registration = serializers.CharField(max_length=30)
    declared_kind = serializers.ChoiceField(
        choices=DeclaredKind.choices, required=False, allow_blank=True, default=""
    )
    device_reported_at = serializers.DateTimeField()
    # servidor − aparelho (segundos) na última medição, e o horário do SERVIDOR em que foi medido.
    clock_offset_seconds = serializers.IntegerField(
        required=False, allow_null=True, default=None, min_value=-30 * 86400, max_value=30 * 86400
    )
    offset_measured_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
    identification = serializers.DictField(required=False, allow_null=True, default=None)
    # Origem do evento: tablet e empresa em que foi feito. Se não conferir com a credencial que o envia
    # (tablet reativado em outra empresa, por exemplo), o evento NUNCA é gravado para outra pessoa.
    origin_device_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    origin_company_id = serializers.IntegerField(required=False, allow_null=True, default=None)

    def validate_registration(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Informe a matrícula.")
        return value


def validate_cnpj(raw: str) -> str:
    if any(not (ch.isascii() and ch.isdigit()) and ch not in ".-/ " for ch in raw):
        raise ValueError("CNPJ inválido.")
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) != 14 or len(set(digits)) == 1:
        raise ValueError("CNPJ inválido.")
    for size, weights in (
        (12, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]),
        (13, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]),
    ):
        total = sum(int(d) * w for d, w in zip(digits[:size], weights, strict=True))
        check = 0 if total % 11 < 2 else 11 - total % 11
        if int(digits[size]) != check:
            raise ValueError("CNPJ inválido.")
    return digits


class EmployerSerializer(serializers.Serializer):
    legal_name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    tax_id_type = serializers.ChoiceField(choices=["CNPJ", "CPF"], required=False, allow_blank=True)
    tax_id = serializers.CharField(max_length=20, required=False, allow_blank=True)
    cei_caepf_cno = serializers.CharField(max_length=20, required=False, allow_blank=True)

    def validate(self, attrs):
        instance = self.context["company"]
        kind = attrs.get("tax_id_type", instance.tax_id_type)
        number = attrs.get("tax_id", instance.tax_id)
        if "tax_id" in attrs or "tax_id_type" in attrs:
            if number:
                if not kind:
                    raise serializers.ValidationError(
                        {"tax_id_type": "Informe se o documento é CNPJ ou CPF."}
                    )
                try:
                    attrs["tax_id"] = (
                        validate_cnpj(number) if kind == "CNPJ" else ops_services.validate_cpf(number)
                    )
                except ValueError as exc:
                    raise serializers.ValidationError({"tax_id": str(exc)}) from exc
                if not attrs["tax_id"]:
                    raise serializers.ValidationError({"tax_id": "Documento inválido."})
            else:
                attrs["tax_id"] = ""
        return attrs


def employer_dict(company, *, mask_document=False) -> dict:
    return {
        "legal_name": company.legal_name,
        "tax_id_type": company.tax_id_type,
        "tax_id": (
            ops_services.mask_cpf(company.tax_id)
            if mask_document and company.tax_id_type == "CPF"
            else company.tax_id
        ),
        "cei_caepf_cno": company.cei_caepf_cno,
    }


def record_dict(record) -> dict:
    """Visão administrativa/terminal de uma marcação. CPF sempre mascarado."""
    return {
        "id": record.pk,
        "nsr": record.nsr,
        "unit": {"id": record.unit_id, "name": record.unit.name},
        "employee": {
            "id": record.employee_id,
            "registration": record.registration,
            "name": record.employee_name,
        },
        "device": {"id": record.device_id, "name": record.device.name},
        "occurred_at": record.occurred_at,
        "occurred_offset_minutes": record.occurred_offset_minutes,
        "occurred_local_date": record.occurred_local_date,
        "recorded_at": record.recorded_at,
        "declared_kind": record.declared_kind,
        "offline": record.offline,
        "clock_skew_seconds": record.clock_skew_seconds,
        "identification_method": record.identification_method,
        "cpf": ops_services.mask_cpf(record.cpf),
        "hash_sha256": record.record_hash,
        "hash_version": record.hash_version,
        "sync_flags": list(record.sync_flags or []),
    }
