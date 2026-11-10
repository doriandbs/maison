from collections.abc import Iterator
from decimal import Decimal
from typing import Any

from django import forms
from django.forms import BoundField
from django.utils.translation import gettext_lazy as _

from apps.banque.models import Categorie


class FormulairePrevisionnel(forms.Form):
    """Un champ montant par catégorie de dépense du foyer, parente ou sous-catégorie.

    Les champs sont construits à partir des catégories fournies par la vue (celles du
    foyer courant) : l'identifiant d'une autre catégorie posté à la main n'a pas de champ.
    """

    A_PARTIR_DE = "suivants"
    PONCTUEL = "ponctuel"

    portee = forms.ChoiceField(
        label=_("Appliquer les montants modifiés"),
        choices=[
            (A_PARTIR_DE, _("à partir de ce mois et pour les suivants")),
            (PONCTUEL, _("à ce mois uniquement")),
        ],
        initial=A_PARTIR_DE,
        widget=forms.RadioSelect,
    )

    def __init__(
        self, *args: Any, categories: list[Categorie], budgets: dict[int, Decimal], **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self.categories = categories
        for categorie in categories:
            self.fields[self._nom(categorie)] = forms.DecimalField(
                label=categorie.nom,
                required=False,
                min_value=Decimal("0"),
                max_digits=12,
                decimal_places=2,
                initial=budgets.get(categorie.pk),
            )

    @staticmethod
    def _nom(categorie: Categorie) -> str:
        return f"categorie_{categorie.pk}"

    @property
    def est_ponctuel(self) -> bool:
        return self.cleaned_data["portee"] == self.PONCTUEL

    def montants(self) -> dict[int, Decimal | None]:
        return {c.pk: self.cleaned_data[self._nom(c)] for c in self.categories}

    def groupes(self) -> Iterator[tuple[BoundField, list[BoundField]]]:
        """Champ de chaque catégorie parente, suivi de ceux de ses sous-catégories."""
        for parente in (c for c in self.categories if c.parent_id is None):
            enfants = [c for c in self.categories if c.parent_id == parente.pk]
            yield self[self._nom(parente)], [self[self._nom(enfant)] for enfant in enfants]
