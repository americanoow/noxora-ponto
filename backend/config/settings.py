"""Configuração do Noxora Ponto. Toda configuração sensível vem de variáveis de ambiente."""

import os
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


DEBUG = env_bool("DJANGO_DEBUG", False)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "").strip()
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "inseguro-somente-desenvolvimento"
    else:
        raise RuntimeError("DJANGO_SECRET_KEY é obrigatório quando DJANGO_DEBUG é falso.")

if not DEBUG and (len(SECRET_KEY) < 50 or len(set(SECRET_KEY)) < 5):
    raise RuntimeError("DJANGO_SECRET_KEY deve ter ao menos 50 caracteres e 5 caracteres distintos.")

_hosts = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,10.0.2.2")
ALLOWED_HOSTS = [h.strip() for h in _hosts.split(",") if h.strip()]
if not DEBUG and (not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS):
    raise RuntimeError("DJANGO_ALLOWED_HOSTS deve listar hosts explícitos fora de debug.")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "apps.core",
    "apps.accounts",
    "apps.companies",
    "apps.operations",
    "apps.devices",
    "apps.audit",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.accounts.middleware.AbsoluteSessionTimeoutMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# PostgreSQL é o banco do produto. SQLite só existe como recurso de desenvolvimento
# quando DATABASE_URL não está definida e não substitui a validação em PostgreSQL.
DATABASES = {
    "default": dj_database_url.config(
        env="DATABASE_URL",
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=60,
    )
}
if not DEBUG and DATABASES["default"]["ENGINE"] != "django.db.backends.postgresql":
    raise RuntimeError("DATABASE_URL deve configurar PostgreSQL fora de debug.")

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "UTC"  # horários são armazenados em UTC; fuso local é tratado por unidade (etapa 3+)
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_THROTTLE_RATES": {
        "login": "10/min",
        "password_reset": "5/hour",
        "device_activation": "10/min",
        "device": "120/min",
    },
}

# Sessões: expiram por inatividade (janela deslizante) e por duração absoluta.
SESSION_COOKIE_AGE = int(os.environ.get("SESSION_IDLE_TIMEOUT_SECONDS", 3600))
SESSION_SAVE_EVERY_REQUEST = True
SESSION_ABSOLUTE_TIMEOUT = int(os.environ.get("SESSION_ABSOLUTE_TIMEOUT_SECONDS", 12 * 3600))
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()
]
PASSWORD_RESET_TIMEOUT = 3600

# Tablets: ativação por código curto, credencial individual com validade e rotação.
DEVICE_ACTIVATION_TTL_MINUTES = 15
DEVICE_CREDENTIAL_TTL_DAYS = 30
DEVICE_ROTATION_GRACE_MINUTES = 10
DEVICE_ONLINE_SECONDS = 300

FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173").rstrip("/")
EMAIL_BACKEND = os.environ.get("DJANGO_EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
if not DEBUG and EMAIL_BACKEND == "django.core.mail.backends.console.EmailBackend":
    # Em desenvolvimento (DEBUG) o console permite ver links de convite; fora dele, tokens iriam para logs.
    raise RuntimeError("Backend console de e-mail proibido fora de debug: expõe tokens de acesso em logs.")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "Noxora Ponto <nao-responda@localhost>")

if not DEBUG:
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
