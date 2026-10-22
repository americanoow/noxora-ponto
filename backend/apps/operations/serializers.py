from rest_framework import serializers

from . import services
from .models import ScheduleDay, Sector, Unit, WorkSchedule


class UnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = Unit
        fields = ["id", "name", "timezone", "address", "is_active"]

    def validate_name(self, value):
        return value.strip()

    def validate_timezone(self, value):
        try:
            return services.validate_timezone(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc


class SectorSerializer(serializers.ModelSerializer):
    unit = serializers.PrimaryKeyRelatedField(queryset=Unit.objects.none())

    class Meta:
        model = Sector
        fields = ["id", "name", "unit", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        company = self.context.get("company")
        if company is not None:  # unidade de outra empresa vira "id inválido"
            self.fields["unit"].queryset = Unit.objects.filter(company=company)
        if self.instance is not None:  # a unidade do setor não muda
            self.fields["unit"].read_only = True

    def validate_name(self, value):
        return value.strip()


class CpfField(serializers.CharField):
    def to_internal_value(self, data):
        try:
            return services.validate_cpf(super().to_internal_value(data))
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc


class EmployeeWriteSerializer(serializers.Serializer):
    registration = serializers.CharField(max_length=30)
    full_name = serializers.CharField(max_length=200)
    cpf = CpfField(max_length=20, required=False, allow_blank=True, default="")
    admission_date = serializers.DateField(required=False, allow_null=True, default=None)
    access_email = serializers.EmailField(required=False, allow_blank=True, default="")

    def validate_registration(self, value):
        return value.strip()

    def validate_full_name(self, value):
        return value.strip()


class EmployeeUpdateSerializer(serializers.Serializer):
    """Matrícula é imutável; só estes campos mudam."""

    full_name = serializers.CharField(max_length=200, required=False)
    cpf = CpfField(max_length=20, required=False, allow_blank=True)
    admission_date = serializers.DateField(required=False, allow_null=True)
    access_email = serializers.EmailField(required=False, allow_blank=True)
    is_active = serializers.BooleanField(required=False)


class AssignmentCreateSerializer(serializers.Serializer):
    unit = serializers.IntegerField()
    sector = serializers.IntegerField(required=False, allow_null=True, default=None)
    valid_from = serializers.DateField()


class ScheduleAssignCreateSerializer(serializers.Serializer):
    schedule = serializers.IntegerField()
    valid_from = serializers.DateField()


class ScheduleDaySerializer(serializers.ModelSerializer):
    class Meta:
        model = ScheduleDay
        fields = ["weekday", "start_time", "end_time", "break_minutes"]
        extra_kwargs = {"weekday": {"max_value": 6, "min_value": 0}, "break_minutes": {"max_value": 480}}

    def validate(self, attrs):
        missing = {
            field: "Campo obrigatório."
            for field in ("weekday", "start_time", "end_time")
            if field not in attrs
        }
        if missing:
            raise serializers.ValidationError(missing)
        if attrs["start_time"] == attrs["end_time"]:
            raise serializers.ValidationError("Início e fim não podem ser iguais.")
        return attrs


class WorkScheduleSerializer(serializers.ModelSerializer):
    days = ScheduleDaySerializer(many=True)

    class Meta:
        model = WorkSchedule
        fields = ["id", "name", "is_active", "days"]

    def validate_days(self, days):
        weekdays = [d["weekday"] for d in days]
        if len(weekdays) != len(set(weekdays)):
            raise serializers.ValidationError("Dia da semana repetido.")
        if not days:
            raise serializers.ValidationError("Informe ao menos um dia.")
        return days

    def validate_name(self, value):
        return value.strip()


def employee_to_dict(employee, *, full_cpf=False):
    assignment = services.current_assignment(employee)
    return {
        "id": employee.pk,
        "registration": employee.registration,
        "full_name": employee.full_name,
        "cpf": employee.cpf if full_cpf else services.mask_cpf(employee.cpf),
        "admission_date": employee.admission_date,
        "is_active": employee.is_active,
        "access_email": employee.access_user.email if employee.access_user_id else "",
        "unit": {"id": assignment.unit_id, "name": assignment.unit.name} if assignment else None,
        "sector": {"id": assignment.sector_id, "name": assignment.sector.name}
        if assignment and assignment.sector_id
        else None,
    }
