from typing import Any

from django import forms
from django.core.exceptions import ImproperlyConfigured

from .models import ModeleDeFoyer
from .perimetre import Perimetre


class FormulaireDeFoyer(forms.ModelForm):
    """ModelForm d'un `ModeleDeFoyer` : l'objet est rattaché au foyer fourni et toutes
    les listes de choix (clés étrangères, M2M) sont restreintes à ce foyer.

    Sans cela, un POST forgé avec l'identifiant d'un compte d'un autre foyer serait
    accepté par la validation standard de Django.
    """

    def __init__(self, *args: Any, foyer: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        perimetre = foyer if isinstance(foyer, Perimetre) else Perimetre.de(foyer)
        modele = type(self.instance)
        if self.instance.pk and not perimetre.contient(self.instance.foyer_id, modele):
            raise ImproperlyConfigured("L'objet modifié n'appartient pas au foyer courant.")
        self.foyer = foyer
        self.perimetre = perimetre
        if not self.instance.pk:
            # Un nouvel objet va dans son propre espace, ou dans le classement du foyer.
            self.instance.foyer = perimetre.foyer_de_creation(modele)
        for nom, champ in self.fields.items():
            if not isinstance(champ, forms.ModelChoiceField):
                continue
            requete = champ.queryset
            if requete is None or not issubclass(requete.model, ModeleDeFoyer):
                raise ImproperlyConfigured(
                    f"{type(self).__name__}.{nom} : seuls des modèles rattachés à un foyer "
                    "peuvent être proposés dans un formulaire de foyer."
                )
            champ.queryset = requete.du_foyer(foyer)  # type: ignore[attr-defined]
