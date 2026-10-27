# Imagem do backend (API + workers). Build: docker build -t noxora-backend backend/
ARG PYTHON_IMAGE=python:3.13-slim
FROM ${PYTHON_IMAGE} AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    BIOMETRIC_MODEL_DIR=/app/models
WORKDIR /app
COPY requirements.txt .
# CA extra opcional (proxy corporativo): docker build --secret id=extra_ca,src=/caminho/ca.crt ...
RUN --mount=type=secret,id=extra_ca,required=false sh -c '\
    if [ -f /run/secrets/extra_ca ]; then export PIP_CERT=/run/secrets/extra_ca; fi; \
    pip install -r requirements.txt' 
COPY . .
# Modelos faciais (OpenCV Zoo) conferidos por SHA-256 durante o build (FETCH_MODELS=0 pula; o motor
# fica indisponível até rodar `manage.py fetch_face_models` com o volume /app/models).
ARG FETCH_MODELS=1
RUN --mount=type=secret,id=extra_ca,required=false sh -c '\
    if [ -f /run/secrets/extra_ca ]; then export SSL_CERT_FILE=/run/secrets/extra_ca; fi; \
    mkdir -p /app/models && if [ "$FETCH_MODELS" = "1" ]; then DJANGO_DEBUG=true python manage.py fetch_face_models; fi \
    && DJANGO_DEBUG=true python manage.py collectstatic --noinput -v0' 
RUN useradd --system --uid 10001 noxora && chown -R noxora /app/models
USER noxora
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health/').status==200 else 1)"
CMD ["gunicorn", "config.wsgi", "--bind", "0.0.0.0:8000", "--workers", "3", "--threads", "4", "--timeout", "60", "--access-logfile", "-"]
