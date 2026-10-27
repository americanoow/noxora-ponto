"""Configuração do Noxora Ponto. Toda configuração sensível vem de variáveis de ambiente."""

import base64
import hashlib
import json
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
    "apps.timeclock",
    "apps.biometrics",
    "apps.attendance",
    "apps.audit",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "apps.biometrics.security.BiometricPrivacyMiddleware",
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
if DEBUG:
    # O painel em desenvolvimento roda no Vite (porta 5173) e o navegador envia esse Origin.
    # Fora de debug as origens precisam ser listadas explicitamente em DJANGO_CSRF_TRUSTED_ORIGINS.
    for _origin in ("http://localhost:5173", "http://127.0.0.1:5173"):
        if _origin not in CSRF_TRUSTED_ORIGINS:
            CSRF_TRUSTED_ORIGINS.append(_origin)
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

# Núcleo de marcação (REP-P). Identificação só por matrícula NÃO é identificação forte: serve ao
# desenvolvimento até a verificação facial (etapa 6). Desligue com TIMECLOCK_ALLOW_REGISTRATION_ONLY=false.
TIMECLOCK_ALLOW_REGISTRATION_ONLY = env_bool("TIMECLOCK_ALLOW_REGISTRATION_ONLY", True)
TIMECLOCK_COLLECTOR_CODE = "01"  # provisório: ver docs/requisitos-rep-p.md, pendência 5
# Número de registro do REP-P no INPI (art. 79, VII / art. 91). Externo: vazio até existir.
REP_P_INPI_REGISTRATION = os.environ.get("REP_P_INPI_REGISTRATION", "").strip()

# Biometria (etapa 6). Nunca guardar imagem: só o template, criptografado com AES-256-GCM.
# BIOMETRIC_KEYS = JSON {"id-da-chave": "<32 bytes em base64>"}; BIOMETRIC_ACTIVE_KEY_ID: chave de escrita.
# Em produção a chave deve vir de um cofre/KMS (etapa 14/15); aqui é variável de ambiente.
BIOMETRIC_ENGINE = os.environ.get("BIOMETRIC_ENGINE", "simulator" if DEBUG else "").strip()
BIOMETRIC_ENGINES = {
    "simulator": "apps.biometrics.engines.SimulatorEngine",
    "opencv": "apps.biometrics.engines_opencv.OpenCVFaceEngine",
}
# Modelos do motor OpenCV (baixados por `manage.py fetch_face_models`, conferidos por SHA-256).
BIOMETRIC_MODEL_DIR = os.environ.get("BIOMETRIC_MODEL_DIR", str(BASE_DIR / ".models"))
# Cosseno mínimo para considerar o mesmo rosto (referência do OpenCV para SFace: 0,363). CALIBRAR.
BIOMETRIC_MATCH_THRESHOLD = float(os.environ.get("BIOMETRIC_MATCH_THRESHOLD", "0.363"))
# Variação mínima de pose (ver engines_opencv.yaw_proxy) entre os quadros do desafio de vivacidade.
BIOMETRIC_LIVENESS_MIN_YAW_DELTA = float(os.environ.get("BIOMETRIC_LIVENESS_MIN_YAW_DELTA", "0.12"))
BIOMETRIC_MAX_FRAMES = 4
# O simulador só é aceito em desenvolvimento (DJANGO_DEBUG=true na carga das configurações).
BIOMETRIC_ALLOW_SIMULATOR = DEBUG
if not DEBUG and BIOMETRIC_ENGINE == "simulator":
    raise RuntimeError("O motor biométrico simulador só pode ser usado com DJANGO_DEBUG=true.")
try:
    BIOMETRIC_KEYS = json.loads(os.environ.get("BIOMETRIC_KEYS", "") or "{}")
    if not isinstance(BIOMETRIC_KEYS, dict):
        raise ValueError
except (ValueError, TypeError):
    raise RuntimeError("BIOMETRIC_KEYS deve ser um objeto JSON válido.") from None
BIOMETRIC_ACTIVE_KEY_ID = os.environ.get("BIOMETRIC_ACTIVE_KEY_ID", "").strip()
if DEBUG and not BIOMETRIC_KEYS:
    BIOMETRIC_KEYS = {
        "dev": base64.b64encode(
            hashlib.sha256(b"noxora-dev-biometric:" + SECRET_KEY.encode()).digest()
        ).decode()
    }
    BIOMETRIC_ACTIVE_KEY_ID = "dev"
try:
    for _key_id, _key in BIOMETRIC_KEYS.items():
        if not isinstance(_key, str) or len(base64.b64decode(_key, validate=True)) != 32:
            raise ValueError
except (ValueError, TypeError):
    raise RuntimeError("Chaves biométricas devem ter 32 bytes em base64 estrito.") from None
if not DEBUG and BIOMETRIC_ENGINE and (BIOMETRIC_ENGINE not in BIOMETRIC_ENGINES or not BIOMETRIC_KEYS):
    raise RuntimeError("Motor biométrico desconhecido ou sem chaves configuradas.")
if BIOMETRIC_KEYS and BIOMETRIC_ACTIVE_KEY_ID not in BIOMETRIC_KEYS:
    raise RuntimeError("BIOMETRIC_ACTIVE_KEY_ID deve apontar para uma chave de BIOMETRIC_KEYS.")
BIOMETRIC_VERIFICATION_TTL_SECONDS = 60  # validade do token de verificação facial (uso único)
BIOMETRIC_LOCKOUT_FAILURES = 5  # falhas seguidas que bloqueiam a verificação facial do funcionário
BIOMETRIC_LOCKOUT_WINDOW_SECONDS = 600
BIOMETRIC_MAX_IMAGE_BYTES = 1_000_000
BIOMETRIC_MAX_IMAGES = 5
EXCEPTION_AUTHORIZATION_TTL_MINUTES = 15

DEFAULT_EXCEPTION_REPORTER_FILTER = "apps.biometrics.security.BiometricExceptionFilter"

# Sincronização offline (etapa 7).
OFFLINE_BATCH_MAX = 50  # eventos por requisição de sincronização
OFFLINE_MAX_AGE_DAYS = 35  # evento mais antigo que isto é recusado (a credencial dura 30 dias)
OFFLINE_FUTURE_TOLERANCE_SECONDS = (
    120  # horário corrigido no futuro além disto é limitado ao recebimento e sinalizado
)
OFFLINE_CLOCK_SKEW_FLAG_SECONDS = 30  # desvio do relógio acima disto é sinalizado (Anexo IX, item 2)
OFFLINE_OFFSET_STALE_HOURS = 24  # desvio medido há mais tempo que isto é sinalizado como defasado
