from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from .espaces import acces_aux_espaces
from .models import Adhesion

CLE_SESSION_FOYER = "foyer_courant_id"
CLE_SESSION_ESPACE = "espace_courant_id"


def _choisir(adhesions: list[Adhesion], foyer_id: int | None) -> Adhesion | None:
    for adhesion in adhesions:
        if adhesion.foyer_id == foyer_id:
            return adhesion
    # Triées foyer principal en tête : c'est lui qui s'ouvre par défaut.
    return adhesions[0] if adhesions else None


class IntergicielFoyerCourant:
    """Pose sur la requête les deux contextes de l'application :

    - `request.adhesions` / `request.adhesion_foyer` : les foyers partagés de l'utilisateur
      et le foyer courant (documents, membres) ;
    - `request.espaces` / `request.adhesion` : les espaces financiers accessibles (le sien,
      puis ceux des autres membres du foyer courant) et celui qui est affiché.

    Tout est relu en base à chaque requête : un membre retiré d'un foyer perd aussitôt
    l'accès au foyer et aux espaces de ses membres, même si sa session les désigne encore.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        partagees: list[Adhesion] = []
        espaces: list[Adhesion] = []
        # Rien n'est chargé tant que la double authentification n'est pas passée.
        if request.user.is_authenticated and getattr(request, "acces_complet", True):
            partagees = list(
                Adhesion.objects.filter(utilisateur=request.user, foyer__personne__isnull=True)
                .select_related("foyer")
                .order_by("-est_principal", "foyer__nom")
            )
        request.adhesions = partagees  # type: ignore[attr-defined]
        adhesion_foyer = _choisir(partagees, request.session.get(CLE_SESSION_FOYER))
        request.adhesion_foyer = adhesion_foyer  # type: ignore[attr-defined]
        if request.user.is_authenticated and getattr(request, "acces_complet", True):
            espaces = acces_aux_espaces(
                request.user,
                adhesion_foyer.foyer if adhesion_foyer else None,
            )
        request.espaces = espaces  # type: ignore[attr-defined]
        request.adhesion = _choisir(  # type: ignore[attr-defined]
            espaces, request.session.get(CLE_SESSION_ESPACE)
        )
        return self.get_response(request)
