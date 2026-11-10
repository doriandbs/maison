from typing import Any

from django import forms
from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _

from .models import Adhesion, Foyer, Role


def roles_attribuables(par: Adhesion) -> list[tuple[str, str | Promise]]:
    """Rôles qu'un membre peut donner : seul un propriétaire peut faire d'autres propriétaires."""
    if par.role == Role.PROPRIETAIRE:
        return list(Role.choices)
    return [choix for choix in Role.choices if choix[0] != Role.PROPRIETAIRE]


class FormulaireFoyer(forms.ModelForm):
    class Meta:
        model = Foyer
        fields = ("nom",)
        labels = {"nom": _("Nom du foyer")}
        help_texts = {"nom": _("Par exemple « Maison », « Appartement en location ».")}


class FormulaireInvitation(forms.Form):
    email = forms.EmailField(label=_("Adresse e-mail"))
    role = forms.ChoiceField(label=_("Rôle"), initial=Role.MEMBRE)

    def __init__(self, *args: Any, par: Adhesion, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["role"].choices = roles_attribuables(par)  # type: ignore[attr-defined]


class FormulaireRole(forms.Form):
    role = forms.ChoiceField(label=_("Rôle"), choices=Role.choices)
