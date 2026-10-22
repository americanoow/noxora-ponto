from rest_framework import serializers

from apps.operations.models import Unit

from . import services
from .models import Device, LocationEvidence


class DeviceSerializer(serializers.ModelSerializer):
    unit_name = serializers.CharField(source="unit.name", read_only=True)
    connectivity = serializers.SerializerMethodField()

    class Meta:
        model = Device
        fields = [
            "id",
            "name",
            "unit",
            "unit_name",
            "status",
            "activated_at",
            "revoked_at",
            "app_version",
            "last_seen_at",
            "connectivity",
            "collect_location",
            "location_justification",
        ]
        read_only_fields = fields

    def get_connectivity(self, obj):
        return services.connectivity(obj)


class DeviceCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    unit = serializers.PrimaryKeyRelatedField(queryset=Unit.objects.none())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        company = self.context.get("company")
        if company is not None:  # unidade de outra empresa vira "id inválido"
            self.fields["unit"].queryset = Unit.objects.filter(company=company, is_active=True)

    def validate_name(self, value):
        return value.strip()


class DeviceUpdateSerializer(DeviceCreateSerializer):
    name = serializers.CharField(max_length=120, required=False)
    unit = serializers.PrimaryKeyRelatedField(queryset=Unit.objects.none(), required=False)
    collect_location = serializers.BooleanField(required=False)
    location_justification = serializers.CharField(max_length=300, required=False, allow_blank=True)


class ActivateSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=32)
    app_version = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    hardware_hint = serializers.CharField(max_length=128, required=False, allow_blank=True, default="")


class HeartbeatSerializer(serializers.Serializer):
    app_version = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")


class LocationSerializer(serializers.Serializer):
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, min_value=-90, max_value=90)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, min_value=-180, max_value=180)
    accuracy_m = serializers.IntegerField(
        required=False, allow_null=True, min_value=0, max_value=100000, default=None
    )
    captured_at = serializers.DateTimeField()


class LocationEvidenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = LocationEvidence
        fields = ["latitude", "longitude", "accuracy_m", "captured_at", "received_at"]
