import time

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.middleware.csrf import get_token
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from rest_framework import serializers, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit import services as audit
from apps.core.throttling import AtomicScopedRateThrottle as ScopedRateThrottle

from . import mfa, totp
from .services import send_password_reset


class CsrfEnforcedAuthentication(SessionAuthentication):
    """Exige token CSRF mesmo em endpoints públicos (evita login CSRF)."""

    def authenticate(self, request):
        self.enforce_csrf(request)
        return None


class PublicView(APIView):
    authentication_classes = [CsrfEnforcedAuthentication]
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(trim_whitespace=False, max_length=256)


def serialize_me(user):
    memberships = user.memberships.filter(is_active=True, company__is_active=True).select_related("company")
    return {
        "id": user.pk,
        "email": user.email,
        "name": user.first_name,
        "is_platform_admin": user.is_platform_admin,
        "mfa_enabled": mfa.enabled(user),
        "memberships": [
            {"id": m.pk, "company_id": m.company_id, "company_name": m.company.name, "role": m.role}
            for m in memberships
        ],
    }


class CsrfView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"csrfToken": get_token(request)})


class LoginView(PublicView):
    throttle_scope = "login"

    def post(self, request):
        data = LoginSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        email = data.validated_data["email"]
        user = authenticate(request, username=email, password=data.validated_data["password"])
        if user is None:
            audit.record(request, "auth.login_failed", actor_email=email.lower())
            return Response({"detail": "E-mail ou senha inválidos."}, status=status.HTTP_400_BAD_REQUEST)
        if mfa.enabled(user):
            # Senha correta, mas a sessão só é criada após o segundo fator.
            request.session.cycle_key()
            request.session["mfa_pending"] = {"user": user.pk, "at": time.time(), "attempts": 0}
            audit.record(request, "auth.mfa_challenge", actor=user)
            return Response({"mfa_required": True})
        login(request, user)
        audit.record(request, "auth.login", actor=user)
        return Response(serialize_me(user))


class MfaVerifyView(PublicView):
    """Segundo passo do login: código do aplicativo autenticador ou de recuperação."""

    throttle_scope = "login"

    def post(self, request):
        pending = request.session.get("mfa_pending")
        if not pending or time.time() - pending.get("at", 0) > mfa.PENDING_SECONDS:
            request.session.pop("mfa_pending", None)
            return Response({"detail": "Faça login novamente."}, status=status.HTTP_400_BAD_REQUEST)
        user = get_user_model().objects.filter(pk=pending["user"], is_active=True).first()
        if user is None or not mfa.check(user, request.data.get("code")):
            pending["attempts"] = pending.get("attempts", 0) + 1
            if pending["attempts"] >= mfa.MAX_PENDING_ATTEMPTS:
                request.session.pop("mfa_pending", None)
            else:
                request.session["mfa_pending"] = pending
            audit.record(request, "auth.mfa_failed", actor=user)
            return Response({"detail": "Código inválido."}, status=status.HTTP_400_BAD_REQUEST)
        request.session.pop("mfa_pending", None)
        login(request, user)
        audit.record(request, "auth.login", actor=user, mfa=True)
        return Response(serialize_me(user))


class MfaSetupView(APIView):
    """POST inicia (segredo mostrado uma vez); PUT confirma com código; DELETE desativa (senha + código)."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            secret = mfa.start_setup(request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {"secret": secret, "otpauth_uri": totp.provisioning_uri(secret, request.user.email)},
            headers={"Cache-Control": "no-store"},
        )

    def put(self, request):
        codes = mfa.confirm_setup(request.user, request.data.get("code"))
        if codes is None:
            return Response({"detail": "Código inválido."}, status=status.HTTP_400_BAD_REQUEST)
        audit.record(request, "auth.mfa_enabled")
        return Response({"recovery_codes": codes}, headers={"Cache-Control": "no-store"})

    def delete(self, request):
        password = request.data.get("password")
        if not isinstance(password, str) or not request.user.check_password(password):
            return Response({"detail": "Senha incorreta."}, status=status.HTTP_400_BAD_REQUEST)
        if not mfa.check(request.user, request.data.get("code")):
            return Response({"detail": "Código inválido."}, status=status.HTTP_400_BAD_REQUEST)
        mfa.disable(request.user)
        audit.record(request, "auth.mfa_disabled")
        return Response(status=status.HTTP_204_NO_CONTENT)


class LogoutView(APIView):
    def post(self, request):
        audit.record(request, "auth.logout")
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(serialize_me(request.user))


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetRequestView(PublicView):
    throttle_scope = "password_reset"

    def post(self, request):
        data = PasswordResetRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user = get_user_model().objects.filter(email__iexact=data.validated_data["email"]).first()
        if user is not None:
            send_password_reset(user)
            audit.record(request, "auth.password_reset_requested", actor=user)
        # Resposta idêntica para existente e inexistente: não revela cadastros.
        return Response({"detail": "Se o e-mail estiver cadastrado, enviaremos as instruções."}, status=202)


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField(max_length=64)
    token = serializers.CharField(max_length=128)
    new_password = serializers.CharField(trim_whitespace=False, max_length=256)


class PasswordResetConfirmView(PublicView):
    throttle_scope = "password_reset"

    def post(self, request):
        data = PasswordResetConfirmSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        invalid = Response({"detail": "Link inválido ou expirado."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            pk = force_str(urlsafe_base64_decode(data.validated_data["uid"]))
            user = get_user_model().objects.get(pk=pk, is_active=True)
        except (ValueError, TypeError, OverflowError, get_user_model().DoesNotExist):
            return invalid
        if not default_token_generator.check_token(user, data.validated_data["token"]):
            return invalid
        try:
            validate_password(data.validated_data["new_password"], user)
        except DjangoValidationError as exc:
            return Response({"new_password": list(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)
        old_password = user.password
        user.set_password(data.validated_data["new_password"])
        with transaction.atomic():
            # Compare-and-swap: duas confirmações que validaram o mesmo hash não podem vencer.
            changed = (
                get_user_model()
                .objects.filter(
                    pk=user.pk,
                    password=old_password,
                    is_active=True,
                    last_login=user.last_login,
                    email=user.email,
                )
                .update(password=user.password)
            )
            if not changed:
                return invalid
            audit.record(request, "auth.password_reset_confirmed", actor=user)
        return Response({"detail": "Senha atualizada."})
