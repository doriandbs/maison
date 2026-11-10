from collections.abc import Callable

from django.http import HttpRequest, HttpResponse


class IntergicielNonIndexe:
    """Demande aux moteurs de recherche de n'indexer aucune page ni aucun fichier.

    L'en-tête couvre aussi ce qui n'est pas du HTML (documents PDF, images). On ne bloque pas
    l'exploration par robots.txt : un moteur qui ne peut pas lire la page ne voit pas non
    plus la consigne « noindex », et peut alors référencer l'adresse seule.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        reponse = self.get_response(request)
        reponse["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        return reponse
