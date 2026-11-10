from collections.abc import Callable

from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit


def limiter_par_ip(taux: str) -> Callable[[type], type]:
    """Limite les POST d'une vue-classe par adresse IP (ex. « 10/h »)."""
    return method_decorator(
        ratelimit(key="ip", rate=taux, method="POST", block=True), name="dispatch"
    )


def limiter_par_utilisateur(taux: str) -> Callable[[type], type]:
    return method_decorator(
        ratelimit(key="user_or_ip", rate=taux, method="POST", block=True), name="dispatch"
    )
