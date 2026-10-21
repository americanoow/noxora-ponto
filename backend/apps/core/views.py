import logging

from django.db import connection
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

logger = logging.getLogger(__name__)


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def health(request):
    """Liveness: o processo responde. Não consulta dependências."""
    return Response({"status": "ok"})


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def ready(request):
    """Readiness: confirma acesso ao banco. Não expõe detalhes do erro ao cliente."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        logger.error("Falha na verificação de prontidão do banco")
        return Response({"status": "indisponivel", "database": "falha"}, status=503)
    return Response({"status": "ok", "database": "ok"})
