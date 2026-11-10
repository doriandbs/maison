from typing import Any

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render

from .sante import base_joignable


def sante(request: HttpRequest) -> JsonResponse:
    if base_joignable():
        return JsonResponse({"etat": "ok"})
    return JsonResponse({"etat": "erreur", "detail": "base de données injoignable"}, status=503)


def trop_de_requetes(request: HttpRequest, exception: Exception) -> HttpResponse:
    return render(request, "socle/trop_de_requetes.html", status=429)


class PageFormulaireMixin:
    """Gabarit commun à tous les écrans de saisie : un titre, un formulaire, un retour."""

    titre: Any = ""
    url_retour: Any = ""

    def get_template_names(self) -> list[str]:
        return ["composants/page_formulaire.html"]

    def get_success_url(self) -> str:
        return str(self.url_retour)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexte = super().get_context_data(**kwargs)  # type: ignore[misc]
        contexte["titre"] = self.titre
        contexte["url_retour"] = self.get_success_url()
        return contexte
