from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create(self, email, password, **extra):
        if not email or not email.strip():
            raise ValueError("O e-mail é obrigatório.")
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        if extra["is_staff"] is not True or extra["is_superuser"] is not True:
            raise ValueError("Superusuário exige is_staff=True e is_superuser=True.")
        return self._create(email, password, **extra)

    def get_by_natural_key(self, username):
        return self.get(email__iexact=username.strip())


class User(AbstractUser):
    """Usuário de acesso ao sistema, identificado por e-mail.

    Não representa funcionário nem vínculo empregatício (etapa 3).
    Empresas e papéis entram na etapa 2.
    """

    username = None
    email = models.EmailField("e-mail", unique=True)
    # Equipe da Noxora. Independe de is_staff/is_superuser e não concede acesso aos dados internos
    # das empresas: só gestão comercial/cadastral de empresas, sempre auditada.
    is_platform_admin = models.BooleanField(default=False)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    objects = UserManager()

    class Meta(AbstractUser.Meta):
        constraints = [models.UniqueConstraint(Lower("email"), name="accounts_user_email_ci_unique")]

    def clean(self):
        super().clean()
        self.email = self.email.strip().lower()

    def save(self, *args, **kwargs):
        self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.email


class TotpDevice(models.Model):
    """Segundo fator (TOTP). O segredo fica cifrado (AES-GCM, chave derivada do SECRET_KEY)."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="totp")
    nonce = models.BinaryField(max_length=12)
    ciphertext = models.BinaryField()
    confirmed_at = models.DateTimeField(null=True, blank=True)
    last_step = models.BigIntegerField(null=True, blank=True)  # impede reuso do mesmo código
    created_at = models.DateTimeField(auto_now_add=True)

    def __repr__(self):
        return f"<TotpDevice user={self.user_id} confirmed={self.confirmed_at is not None}>"


class RecoveryCode(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="recovery_codes")
    code_hash = models.CharField(max_length=64)
    used_at = models.DateTimeField(null=True, blank=True)
