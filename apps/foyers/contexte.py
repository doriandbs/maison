from typing import Any

from django.http import HttpRequest

from .models import Role


def foyer_courant(request: HttpRequest) -> dict[str, Any]:
    espace = getattr(request, "adhesion", None)
    # Dans une vue « foyer » (documents, membres), droits et rôle sont ceux du foyer partagé ;
    # ailleurs, ceux de l'espace financier affiché.
    adhesion = getattr(request, "adhesion_active", espace)
    return {
        "adhesion_courante": adhesion,
        "adhesion_espace": espace,
        "adhesion_foyer": getattr(request, "adhesion_foyer", None),
        "adhesions": getattr(request, "adhesions", []),
        "espaces": getattr(request, "espaces", []),
        "peut_modifier": adhesion is not None and adhesion.a_au_moins(Role.MEMBRE),
        "peut_administrer": adhesion is not None and adhesion.a_au_moins(Role.ADMINISTRATEUR),
    }
