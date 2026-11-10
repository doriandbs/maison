from __future__ import annotations

from typing import TYPE_CHECKING, Self

from django.db import models
from django.utils.translation import gettext_lazy as _

if TYPE_CHECKING:
    from apps.foyers.models import Foyer


class ModeleHorodate(models.Model):
    cree_le = models.DateTimeField(_("créé le"), auto_now_add=True)
    modifie_le = models.DateTimeField(_("modifié le"), auto_now=True)

    class Meta:
        abstract = True


class RequeteDeFoyer(models.QuerySet):
    def du_foyer(self, foyer: Foyer) -> Self:
        return self.filter(foyer=foyer)


GestionnaireDeFoyer = models.Manager.from_queryset(RequeteDeFoyer)


class ModeleDeFoyer(ModeleHorodate):
    """Base de toute donnée métier : chaque ligne appartient à un foyer et un seul.

    Les vues n'accèdent à ces modèles qu'à travers `objects.du_foyer(...)`
    (voir `apps.foyers.acces.VueDeFoyerMixin`).
    """

    foyer = models.ForeignKey(
        "foyers.Foyer",
        verbose_name=_("foyer"),
        on_delete=models.CASCADE,
        related_name="+",
    )

    objects = GestionnaireDeFoyer()

    class Meta:
        abstract = True
