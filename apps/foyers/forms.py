from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Foyer, Role

ROLES_INVITABLES = [choix for choix in Role.choices if choix[0] != Role.PROPRIETAIRE]


class FormulaireFoyer(forms.ModelForm):
    class Meta:
        model = Foyer
        fields = ("nom",)
        labels = {"nom": _("Nom du foyer")}
        help_texts = {"nom": _("Par exemple « Maison », « Appartement en location ».")}


class FormulaireInvitation(forms.Form):
    email = forms.EmailField(label=_("Adresse e-mail"))
    role = forms.ChoiceField(label=_("Rôle"), choices=ROLES_INVITABLES, initial=Role.MEMBRE)


class FormulaireRole(forms.Form):
    role = forms.ChoiceField(label=_("Rôle"), choices=Role.choices)
