from django import forms
from django.contrib.auth.forms import AuthenticationForm, BaseUserCreationForm
from django.utils.translation import gettext_lazy as _

from .models import Utilisateur


class FormulaireInscription(BaseUserCreationForm):
    first_name = forms.CharField(label=_("Prénom"), max_length=150)

    class Meta:
        model = Utilisateur
        fields = ("first_name", "email")

    def clean_email(self) -> str:
        return self.cleaned_data["email"].strip().lower()


class FormulaireConnexion(AuthenticationForm):
    def clean_username(self) -> str:
        return self.cleaned_data["username"].strip().lower()
