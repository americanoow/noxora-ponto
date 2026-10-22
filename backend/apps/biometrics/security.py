"""Limites antes do parse de JSON e supressão de dados sensíveis em relatórios Django."""

import io

from django.conf import settings
from django.http import JsonResponse
from django.views.debug import SafeExceptionReporterFilter
from rest_framework.exceptions import ParseError
from rest_framework.parsers import JSONParser


class BoundedJSONParser(JSONParser):
    def parse(self, stream, media_type=None, parser_context=None):
        limit = settings.BIOMETRIC_MAX_IMAGE_BYTES * settings.BIOMETRIC_MAX_IMAGES * 4 // 3 + 65536
        data = stream.read(limit + 1)
        if len(data) > limit:
            raise ParseError("Requisição grande demais.")
        result = super().parse(io.BytesIO(data), media_type, parser_context)
        if not isinstance(result, dict):
            raise ParseError("Envie um objeto JSON.")
        return result


def sensitive_path(path):
    return any(part in path for part in ("/biometric/", "/face/", "/identification-exceptions/", "/punches/"))


class BiometricExceptionFilter(SafeExceptionReporterFilter):
    def get_traceback_frame_variables(self, request, tb_frame):
        if request is not None and sensitive_path(request.path):
            return []
        module = tb_frame.f_globals.get("__name__", "")
        if module.startswith("apps.biometrics"):
            return []
        return super().get_traceback_frame_variables(request, tb_frame)


class BiometricPrivacyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if sensitive_path(request.path):
            response["Cache-Control"] = "no-store"
        return response

    def process_exception(self, request, exception):
        if sensitive_path(request.path):
            # Não produzir traceback HTTP/log com corpo, código ou exceção do motor.
            return JsonResponse({"detail": "Operação indisponível."}, status=500)
        return None
