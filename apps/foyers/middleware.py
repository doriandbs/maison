from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from .models import Adhesion

CLE_SESSION_FOYER = "foyer_courant_id"


def _choisir(adhesions: list[Adhesion], foyer_id: int | None) -> Adhesion | None:
    for adhesion in adhesions:
        if adhesion.foyer_id == foyer_id:
            return adhesion
    # Triées foyer principal en tête : c'est lui qui s'ouvre par défaut.
    return adhesions[0] if adhesions else None


class IntergicielFoyerCourant:
    """Pose `request.adhesions` et `request.adhesion` (celle du foyer courant).

    L'appartenance est relue en base à chaque requête : un membre retiré perd
    l'accès immédiatement, même si sa session désigne encore ce foyer.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        adhesions: list[Adhesion] = []
        if request.user.is_authenticated:
            adhesions = list(
                Adhesion.objects.filter(utilisateur=request.user)
                .select_related("foyer")
                .order_by("-est_principal", "foyer__nom")
            )
        request.adhesions = adhesions  # type: ignore[attr-defined]
        request.adhesion = _choisir(  # type: ignore[attr-defined]
            adhesions, request.session.get(CLE_SESSION_FOYER)
        )
        return self.get_response(request)
