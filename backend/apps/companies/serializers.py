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
    name = serializers.CharField(source="user.first_name", read_only=True)

    class Meta:
        model = Membership
        fields = ["id", "email", "name", "role", "is_active"]


class MembershipCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    role = serializers.ChoiceField(choices=Role.choices)


class MembershipUpdateSerializer(serializers.Serializer):
    """Apenas papel e situação. Qualquer outro campo enviado é ignorado."""

    role = serializers.ChoiceField(choices=Role.choices, required=False)
    is_active = serializers.BooleanField(required=False)
