from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse

from . import double_auth

# Seules pages accessibles entre le mot de passe et le code.
ROUTES_PENDANT_LA_VERIFICATION = frozenset(
    {
        "utilisateurs:verification",
        "utilisateurs:activer_double_auth",
        "utilisateurs:deconnexion",
        "sante",
    }
)


class IntergicielDoubleAuthentification:
    """Après le mot de passe, la session n'ouvre rien tant que le code n'est pas saisi.

    Pose `request.acces_complet`, que l'intergiciel du foyer courant consulte : sans accès
    complet, aucun foyer n'est chargé (pas même son nom dans le menu).
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        utilisateur = request.user
        if (
            utilisateur.is_authenticated
            and not double_auth.est_verifie(utilisateur)
            and double_auth.appareil_de_confiance(request, utilisateur)
        ):
            appareil = double_auth.application(utilisateur)
            if appareil is not None:
                double_auth.valider_session(request, appareil)
        request.acces_complet = double_auth.acces_complet(request)  # type: ignore[attr-defined]
        return self.get_response(request)

    def process_view(
        self, request: HttpRequest, vue: Callable[..., Any], args: Any, kwargs: Any
    ) -> HttpResponse | None:
        if not request.user.is_authenticated or request.acces_complet:  # type: ignore[attr-defined]
            return None
        if request.resolver_match and request.resolver_match.view_name in (
            ROUTES_PENDANT_LA_VERIFICATION
        ):
            return None
        etape = (
            "utilisateurs:verification"
            if double_auth.est_configuree(request.user)
            else "utilisateurs:activer_double_auth"
        )
        return redirect(f"{reverse(etape)}?{urlencode({'next': request.get_full_path()})}")
