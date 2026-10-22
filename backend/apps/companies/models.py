from django.conf import settings
from django.db import models


class Company(models.Model):
    name = models.CharField("nome", max_length=200)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # Dados do empregador exigidos no Comprovante de Registro de Ponto (Portaria 671, art. 79, III).
    # Alterações são auditadas com valores anteriores e novos.
    legal_name = models.CharField("razão social ou nome", max_length=200, blank=True)
    tax_id_type = models.CharField(max_length=4, blank=True, choices=[("CNPJ", "CNPJ"), ("CPF", "CPF")])
    tax_id = models.CharField("CNPJ/CPF (só dígitos)", max_length=14, blank=True)
    cei_caepf_cno = models.CharField("CEI/CAEPF/CNO", max_length=20, blank=True)

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

    O papel vale somente dentro da empresa. Gestores veem apenas funcionários cuja lotação atual
    esteja em `scope_units` ou `scope_sectors`; escopo vazio não concede acesso a dados operacionais.
    Administradores da empresa não usam escopo.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="memberships")
    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="memberships")
    role = models.CharField(max_length=20, choices=Role.choices)
    name = models.CharField(max_length=150, blank=True, default="")
    is_active = models.BooleanField(default=True)
    scope_units = models.ManyToManyField("operations.Unit", blank=True, related_name="+")
    scope_sectors = models.ManyToManyField("operations.Sector", blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(fields=["user", "company"], name="uniq_membership_user_company")
        ]
