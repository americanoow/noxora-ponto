from django.urls import path

from . import views

urlpatterns = [
    path(
        "employees/<int:employee_id>/biometric/", views.BiometricStatusView.as_view(), name="biometric-status"
    ),
    path(
        "employees/<int:employee_id>/biometric/consent/",
        views.ConsentView.as_view(),
        name="biometric-consent",
    ),
    path(
        "employees/<int:employee_id>/biometric/enroll/", views.EnrollView.as_view(), name="biometric-enroll"
    ),
    path(
        "employees/<int:employee_id>/identification-exceptions/",
        views.ExceptionView.as_view(),
        name="identification-exception",
    ),
    path("identification/", views.IdentificationModeView.as_view(), name="identification-mode"),
    path("me/biometric/", views.MyBiometricView.as_view(), name="my-biometric"),
]

device_urlpatterns = [
    path("face/challenge/", views.FaceChallengeView.as_view(), name="device-face-challenge"),
    path("face/verify/", views.FaceVerifyView.as_view(), name="device-face-verify"),
]
