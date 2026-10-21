from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode


def send_password_reset(user, *, invite: bool = False):
    """Envia o link de definição de senha. Usuários inativos não recebem."""
    if not user.is_active:
        return
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    link = f"{settings.FRONTEND_URL}/redefinir-senha?uid={uid}&token={token}"
    subject = "Seu acesso ao Noxora Ponto" if invite else "Redefinição de senha do Noxora Ponto"
    send_mail(subject, f"Defina sua senha em: {link}\n\nO link expira em 1 hora.", None, [user.email])


def get_or_invite_user(email: str, name: str = ""):
    """Retorna (usuário, criado). Usuários novos nascem sem senha utilizável e recebem convite.

    Usuário já existente não tem nome nem senha alterados por quem convida.
    """
    User = get_user_model()
    existing = User.objects.filter(email__iexact=email).first()
    if existing:
        return existing, False
    user = User.objects.create_user(email, None, first_name=name[:150])
    return user, True
