from typing import Any

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


class FormulaireCode(forms.Form):
    code = forms.CharField(
        label=_("Code de vérification"),
        max_length=20,
        help_text=_("Les 6 chiffres affichés par votre application, ou un code de secours."),
        widget=forms.TextInput(
            attrs={"autocomplete": "one-time-code", "autofocus": True, "spellcheck": "false"}
        ),
    )
    memoriser = forms.BooleanField(
        label=_("Se souvenir de cet appareil pendant 30 jours"), required=False
    )


class FormulaireActivation(forms.Form):
    code = forms.CharField(
        label=_("Code affiché par l'application"),
        max_length=10,
        widget=forms.TextInput(
            attrs={"autocomplete": "one-time-code", "inputmode": "numeric", "autofocus": True}
        ),
    )


class FormulaireConfirmationMotDePasse(forms.Form):
    """Confirme une action sensible même si la session est déjà ouverte."""

    mot_de_passe = forms.CharField(
        label=_("Mot de passe actuel"),
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )

    def __init__(self, *args: Any, utilisateur: Utilisateur, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.utilisateur = utilisateur

    def clean_mot_de_passe(self) -> str:
        mot_de_passe = self.cleaned_data["mot_de_passe"]
        if not self.utilisateur.check_password(mot_de_passe):
            raise forms.ValidationError(_("Mot de passe incorrect."))
        return mot_de_passe
