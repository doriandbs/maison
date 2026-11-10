from typing import Any

from django.contrib.auth.mixins import AccessMixin
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.http import HttpRequest
from django.shortcuts import redirect

from apps.socle.models import RequeteDeFoyer

from .models import Adhesion, Foyer, Role

METHODES_DE_LECTURE = frozenset({"GET", "HEAD", "OPTIONS"})


class AccesFoyerMixin(AccessMixin):
    """Exige une session ouverte, un foyer courant et un rôle suffisant.

    Par défaut tout membre peut lire et il faut être au moins « membre » pour
    modifier : le rôle « lecture seule » est donc refusé sur tout POST.
    """

    role_lecture: str = Role.LECTEUR
    role_ecriture: str = Role.MEMBRE

    adhesion: Adhesion
    foyer: Foyer

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> Any:
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        adhesion: Adhesion | None = getattr(request, "adhesion", None)
        if adhesion is None:
            return redirect("foyers:liste")
        role_requis = (
            self.role_lecture if request.method in METHODES_DE_LECTURE else self.role_ecriture
        )
        if not adhesion.a_au_moins(role_requis):
            raise PermissionDenied
        self.adhesion = adhesion
        self.foyer = adhesion.foyer
        return super().dispatch(request, *args, **kwargs)  # type: ignore[misc]


class VueDeFoyerMixin(AccesFoyerMixin):
    """Pour les vues génériques sur un `ModeleDeFoyer` : le queryset est toujours
    restreint au foyer courant, donc l'objet d'un autre foyer répond 404."""

    def get_queryset(self) -> RequeteDeFoyer:
        requete = super().get_queryset()  # type: ignore[misc]
        if not isinstance(requete, RequeteDeFoyer):
            raise ImproperlyConfigured(
                f"{type(self).__name__} : le modèle doit hériter de ModeleDeFoyer."
            )
        return requete.du_foyer(self.foyer)
