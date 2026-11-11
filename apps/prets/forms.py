from datetime import date
from decimal import Decimal
from typing import Any

from django import forms
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.banque.forms import ChampDate
from apps.foyers.espaces import proches
from apps.socle.forms import FormulaireDeFoyer
from apps.utilisateurs.models import Utilisateur

from .models import EffetAnticipe, Pret, RemboursementAnticipe


class FormulairePret(FormulaireDeFoyer):
    premiere_echeance = ChampDate(
        label=_("Date de la première échéance"),
        help_text=_("Le premier prélèvement, même s'il ne contient que l'assurance (différé)."),
    )
    signe_le = ChampDate(
        label=_("Date de signature"),
        required=False,
        help_text=_(
            "Ou du premier déblocage des fonds : le crédit compte à partir de cette date. "
            "Vide : un mois avant la première échéance."
        ),
    )

    class Meta:
        model = Pret
        fields = (
            "nom",
            "etablissement",
            "capital",
            "taux_annuel",
            "duree_mois",
            "signe_le",
            "premiere_echeance",
            "assurance_mensuelle",
            "type_differe",
            "differe_mois",
            "compte",
            "valeur_bien",
        )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        comptes = self.fields["compte"]
        comptes.queryset = comptes.queryset.filter(  # type: ignore[attr-defined]
            Q(archive_le__isnull=True) | Q(pk=self.instance.compte_id)
        )
        # Ajouté après la vérification de FormulaireDeFoyer : ce sont des personnes, pas des
        # données d'un foyer. Seules celles avec qui l'on partage un foyer sont proposées.
        titulaire = self.foyer.personne
        self.fields["co_emprunteurs"] = forms.ModelMultipleChoiceField(
            label=_("Co-emprunteurs"),
            queryset=proches(titulaire) if titulaire else Utilisateur.objects.none(),
            required=False,
            widget=forms.CheckboxSelectMultiple,
            help_text=_(
                "Le crédit apparaîtra aussi dans leurs finances ; chacun en compte une part "
                "égale dans son patrimoine."
            ),
        )
        self.fields["co_emprunteurs"].label_from_instance = (  # type: ignore[attr-defined]
            lambda personne: personne.first_name or personne.email
        )
        if self.instance.pk:
            self.initial["co_emprunteurs"] = list(self.instance.co_emprunteurs.all())

    def save(self, commit: bool = True) -> Pret:
        pret = super().save(commit=commit)
        if commit:
            pret.co_emprunteurs.set(self.cleaned_data["co_emprunteurs"])
        return pret


class FormulaireAnticipe(FormulaireDeFoyer):
    date = ChampDate(label=_("Date"), initial=date.today)

    class Meta:
        model = RemboursementAnticipe
        fields = ("date", "montant", "effet")


class FormulaireSimulation(forms.Form):
    """Même champs qu'un remboursement réel, mais rien n'est enregistré."""

    date = ChampDate(label=_("Date"), initial=date.today)
    montant = forms.DecimalField(
        label=_("Montant"), max_digits=12, decimal_places=2, min_value=Decimal("0.01")
    )
    effet = forms.ChoiceField(
        label=_("Effet"), choices=EffetAnticipe.choices, initial=EffetAnticipe.DUREE
    )
