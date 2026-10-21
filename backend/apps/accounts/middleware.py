import time

from django.conf import settings
from django.contrib.auth import logout
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver


@receiver(user_logged_in)
def mark_login_time(sender, request, user, **kwargs):
    if request is not None and hasattr(request, "session"):
        request.session["login_at"] = time.time()


class AbsoluteSessionTimeoutMiddleware:
    """Encerra sessões mais antigas que SESSION_ABSOLUTE_TIMEOUT, mesmo com uso contínuo.

    O tempo ocioso é tratado pelo SESSION_COOKIE_AGE com SESSION_SAVE_EVERY_REQUEST.
    Sessões sem marca de login são tratadas como inválidas.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            login_at = request.session.get("login_at")
            if login_at is None or time.time() - login_at > settings.SESSION_ABSOLUTE_TIMEOUT:
                logout(request)
        return self.get_response(request)
