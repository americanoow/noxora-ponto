import pytest
from django.contrib.auth import authenticate, get_user_model
from django.db import IntegrityError, transaction

User = get_user_model()
pytestmark = pytest.mark.django_db


def test_usuario_normal_e_autenticacao_por_email():
    user = User.objects.create_user(" Teste@Exemplo.com ", "senha-longa-123")
    assert user.email == "teste@exemplo.com"
    assert not user.is_staff and not user.is_superuser
    assert user.check_password("senha-longa-123")
    assert authenticate(email="TESTE@EXEMPLO.COM", password="senha-longa-123") == user
    user.is_active = False
    user.save()
    assert authenticate(email=user.email, password="senha-longa-123") is None


@pytest.mark.parametrize("email", [None, "", "   "])
def test_email_obrigatorio(email):
    with pytest.raises(ValueError):
        User.objects.create_user(email)


def test_senha_ausente_nao_pode_autenticar():
    assert not User.objects.create_user("teste@exemplo.com").has_usable_password()


@pytest.mark.parametrize("field", ["is_staff", "is_superuser"])
def test_superusuario_rejeita_flags_falsas(field):
    with pytest.raises(ValueError):
        User.objects.create_superuser("admin@exemplo.com", **{field: False})
    assert not User.objects.exists()


def test_superusuario_tem_permissoes():
    user = User.objects.create_superuser("admin@exemplo.com", "senha-longa-123")
    assert user.is_staff and user.is_superuser and user.is_active


def test_email_unico_no_banco_mesmo_sem_save():
    User.objects.create_user("teste@exemplo.com")
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.bulk_create([User(email="TESTE@EXEMPLO.COM")])


def test_save_e_clean_normalizam_email():
    user = User(email=" Teste@Exemplo.com ")
    user.clean()
    assert user.email == "teste@exemplo.com"
    user.email = " Outro@Exemplo.com "
    user.save()
    user.refresh_from_db()
    assert user.email == "outro@exemplo.com"
