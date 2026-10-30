from rest_framework import serializers

from .models import Company, Membership, Role


class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = ["id", "name", "is_active", "created_at"]
        read_only_fields = ["id", "created_at"]


class CompanyCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    admin_email = serializers.EmailField()
    admin_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")


class CompanyUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200, required=False)
    is_active = serializers.BooleanField(required=False)


class MembershipSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source="user.email", read_only=True)
    name = serializers.CharField(read_only=True)
    scope_unit_ids = serializers.SerializerMethodField()
    scope_sector_ids = serializers.SerializerMethodField()

    class Meta:
        model = Membership
        fields = [
            "id",
            "email",
            "name",
            "role",
            "is_active",
            "can_request_adjustments",
            "can_decide_requests",
            "scope_unit_ids",
            "scope_sector_ids",
        ]

    def get_scope_unit_ids(self, obj):
        return sorted(u.pk for u in obj.scope_units.all())

    def get_scope_sector_ids(self, obj):
        return sorted(s.pk for s in obj.scope_sectors.all())


class MembershipCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    role = serializers.ChoiceField(choices=Role.choices)
    can_request_adjustments = serializers.BooleanField(required=False, default=True)
    can_decide_requests = serializers.BooleanField(required=False, default=True)


class MembershipUpdateSerializer(serializers.Serializer):
    """Apenas papel e situação. Qualquer outro campo enviado é ignorado."""

    role = serializers.ChoiceField(choices=Role.choices, required=False)
    is_active = serializers.BooleanField(required=False)
    can_request_adjustments = serializers.BooleanField(required=False)
    can_decide_requests = serializers.BooleanField(required=False)
    scope_unit_ids = serializers.ListField(child=serializers.IntegerField(), required=False, max_length=200)
    scope_sector_ids = serializers.ListField(child=serializers.IntegerField(), required=False, max_length=500)
