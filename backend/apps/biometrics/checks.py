from django.conf import settings
from django.core.checks import Error, register


@register(deploy=True)
def biometric_deployment_checks(app_configs, **kwargs):
    errors = []
    if settings.BIOMETRIC_ALLOW_SIMULATOR or settings.BIOMETRIC_ENGINE == "simulator":
        errors.append(Error("Simulador biométrico habilitado: implantação proibida.", id="biometrics.E001"))
    if settings.BIOMETRIC_ENGINE:
        if settings.BIOMETRIC_ENGINE not in settings.BIOMETRIC_ENGINES:
            errors.append(Error("Motor biométrico não registrado.", id="biometrics.E002"))
        if not settings.BIOMETRIC_KEYS or settings.BIOMETRIC_ACTIVE_KEY_ID not in settings.BIOMETRIC_KEYS:
            errors.append(Error("Motor sem chave biométrica ativa.", id="biometrics.E003"))
    return errors


@register()
def biometric_model_checks(app_configs, **kwargs):
    """Motor OpenCV configurado sem os modelos conferidos: avisar já na inicialização."""
    from django.core.checks import Warning as CheckWarning

    if settings.BIOMETRIC_ENGINE != "opencv":
        return []
    from . import engines

    try:
        from . import engines_opencv

        engines_opencv.model_path("detector")
        engines_opencv.model_path("recognizer")
    except engines.EngineUnavailable:
        return [
            CheckWarning(
                "Modelos faciais ausentes ou adulterados: rode `manage.py fetch_face_models`.",
                id="biometrics.W001",
            )
        ]
    return []
