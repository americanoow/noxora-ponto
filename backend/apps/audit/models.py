from django.conf import settings
from django.db import models


class AppendOnlyError(Exception):
    pass


class AuditQuerySet(models.QuerySet):
    def bulk_create(self, objs, **kwargs):
        if kwargs.get("update_conflicts"):
            raise AppendOnlyError("Registros de auditoria não podem ser alterados.")
        return super().bulk_create(objs, **kwargs)

    def update(self, **kwargs):
        raise AppendOnlyError("Registros de auditoria não podem ser alterados.")

    def delete(self):
        raise AppendOnlyError("Registros de auditoria não podem ser apagados.")


class AuditLog(models.Model):
    """Trilha de auditoria somente de inclusão. Nunca guarda senhas, tokens ou biometria."""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    actor_email = models.CharField(max_length=254, blank=True)  # preservado mesmo se o usuário mudar
    company = models.ForeignKey(
        "companies.Company", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    action = models.CharField(max_length=80, db_index=True)
    target_type = models.CharField(max_length=80, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    objects = AuditQuerySet.as_manager()

    class Meta:
        ordering = ["-id"]
        indexes = [models.Index(fields=["company", "-id"])]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise AppendOnlyError("Registros de auditoria não podem ser alterados.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AppendOnlyError("Registros de auditoria não podem ser apagados.")
