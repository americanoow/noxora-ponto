from django.conf import settings
from django.db import models


class Company(models.Model):
    name = models.CharField("nome", max_length=200)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "id"]

    def __str__(self):
        return self.name


class Role(models.TextChoices):
    COMPANY_ADMIN = "company_admin", "Administrador da empresa"
    MANAGER = "manager", "Gestor"
    EMPLOYEE = "employee", "Funcionário"


class Membership(models.Model):
    """Vínculo de acesso entre um usuário e uma empresa, com papel próprio.

    O papel vale somente dentro da empresa. Escopo por unidade/setor entra na etapa 3,
    quando essas entidades existirem.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="memberships")
    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="memberships")
    role = models.CharField(max_length=20, choices=Role.choices)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(fields=["user", "company"], name="uniq_membership_user_company")
        ]
