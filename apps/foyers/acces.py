from typing import Any

from django.contrib.auth.mixins import AccessMixin
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.http import HttpRequest
from django.shortcuts import redirect

from apps.socle.models import RequeteDeFoyer

from .models import Adhesion, Role

METHODES_DE_LECTURE = frozenset({"GET", "HEAD", "OPTIONS"})


class AccesFoyerMixin(AccessMixin):
    """Exige une session ouverte, un foyer courant et un rôle suffisant.

    Par défaut tout membre peut lire et il faut être au moins « membre » pour
    modifier : le rôle « lecture seule » est donc refusé sur tout POST.
    """

    role_lecture: str = Role.LECTEUR
    role_ecriture: str = Role.MEMBRE
    # « finances » : l'espace financier affiché (le sien ou celui d'un membre du foyer).
    # « foyer » : le foyer partagé courant (documents, membres, invitations).
    portee: str = "finances"

    adhesion: Adhesion
    foyer: Any  # Foyer, ou Perimetre pour les écrans de finances

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> Any:
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        attribut = "adhesion_foyer" if self.portee == "foyer" else "adhesion"
        adhesion: Adhesion | None = getattr(request, attribut, None)
        if adhesion is None:
            return redirect("foyers:liste")
        # Lu par le processeur de contexte : rôle et droits affichés suivent la vue.
        request.adhesion_active = adhesion  # type: ignore[attr-defined]
        perimetre = getattr(request, "perimetre", None)
        role_requis = (
            self.role_lecture if request.method in METHODES_DE_LECTURE else self.role_ecriture
        )
        if not adhesion.a_au_moins(role_requis):
            raise PermissionDenied
        self.adhesion = adhesion
        # Écrans de finances : `self.foyer` est le périmètre (tous les espaces du foyer et son
        # classement), que `du_foyer()` et `FormulaireDeFoyer` savent filtrer.
        self.foyer = perimetre if self.portee == "finances" and perimetre else adhesion.foyer
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


class VueFormulaireDeFoyerMixin(AccesFoyerMixin):
    """Transmet le foyer courant au formulaire (voir `socle.forms.FormulaireDeFoyer`)."""

    def get_form_kwargs(self) -> dict[str, Any]:
        arguments = super().get_form_kwargs()  # type: ignore[misc]
        arguments["foyer"] = self.foyer
        return arguments
