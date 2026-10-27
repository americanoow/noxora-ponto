from django.urls import path

from . import views

urlpatterns = [
    path("csrf/", views.CsrfView.as_view(), name="auth-csrf"),
    path("login/", views.LoginView.as_view(), name="auth-login"),
    path("logout/", views.LogoutView.as_view(), name="auth-logout"),
    path("mfa/verify/", views.MfaVerifyView.as_view(), name="auth-mfa-verify"),
    path("mfa/", views.MfaSetupView.as_view(), name="auth-mfa"),
    path("me/", views.MeView.as_view(), name="auth-me"),
    path("password-reset/", views.PasswordResetRequestView.as_view(), name="auth-password-reset"),
    path(
        "password-reset/confirm/",
        views.PasswordResetConfirmView.as_view(),
        name="auth-password-reset-confirm",
    ),
]
