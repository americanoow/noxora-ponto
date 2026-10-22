from django.apps import AppConfig


class BiometricsConfig(AppConfig):
    name = "apps.biometrics"
    label = "biometrics"

    def ready(self):
        # Registra os métodos de identificação da marcação (contrato definido em apps.timeclock).
        from apps.timeclock import services as timeclock

        from . import services

        timeclock.PROVIDERS.setdefault(services.FaceProvider.method, services.FaceProvider())
        timeclock.PROVIDERS.setdefault(services.ExceptionProvider.method, services.ExceptionProvider())
