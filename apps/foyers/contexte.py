from typing import Any

from django.http import HttpRequest

from .models import Role


def foyer_courant(request: HttpRequest) -> dict[str, Any]:
    adhesion = getattr(request, "adhesion", None)
    return {
        "adhesion_courante": adhesion,
        "adhesions": getattr(request, "adhesions", []),
        "peut_administrer": adhesion is not None and adhesion.a_au_moins(Role.ADMINISTRATEUR),
    }
