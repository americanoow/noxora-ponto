"""Recifra os templates com a chave ativa (BIOMETRIC_ACTIVE_KEY_ID).

Procedimento: (1) acrescente a nova chave em BIOMETRIC_KEYS mantendo as antigas; (2) aponte
BIOMETRIC_ACTIVE_KEY_ID para ela; (3) rode este comando; (4) confirme `--check` sem pendências; (5) só
então remova a chave antiga da configuração. Templates excluídos não têm conteúdo e são ignorados.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.biometrics import crypto
from apps.biometrics.models import BiometricTemplate, TemplateStatus


class Command(BaseCommand):
    help = "Recifra templates biométricos com a chave ativa. --check só conta os pendentes."

    def add_arguments(self, parser):
        parser.add_argument("--check", action="store_true")

    def handle(self, *args, check=False, **options):
        from django.conf import settings

        active = settings.BIOMETRIC_ACTIVE_KEY_ID
        if not active:
            raise CommandError("BIOMETRIC_ACTIVE_KEY_ID não configurada.")
        pending = BiometricTemplate.objects.filter(status=TemplateStatus.ACTIVE).exclude(key_id=active)
        if check:
            self.stdout.write(f"templates com chave antiga: {pending.count()}")
            return
        done = failed = 0
        for template_id in pending.values_list("pk", flat=True):
            with transaction.atomic():
                t = BiometricTemplate.objects.select_for_update().get(pk=template_id)
                if t.status != TemplateStatus.ACTIVE or t.key_id == active:
                    continue
                aad = crypto.make_aad(t.company_id, t.employee_id, t.engine)
                try:
                    plain = crypto.decrypt(t.key_id, t.nonce, t.ciphertext, aad)
                except (crypto.CryptoUnavailable, crypto.DecryptionFailed):
                    failed += 1
                    continue
                t.key_id, t.nonce, t.ciphertext = crypto.encrypt(plain, aad)
                del plain
                t.save(update_fields=["key_id", "nonce", "ciphertext"])
                done += 1
        self.stdout.write(f"recifrados: {done}; falhas (chave indisponível): {failed}")
        if failed:
            raise CommandError("Há templates cuja chave não está configurada.")
