from datetime import date
from decimal import Decimal
from typing import Any

from django import forms
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.foyers.models import Foyer
from apps.socle.forms import FormulaireDeFoyer

from .models import Categorie, Compte, Operation


class ChampDate(forms.DateField):
    widget = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class ChampMontantPositif(forms.DecimalField):
    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("label", _("Montant"))
        super().__init__(max_digits=12, decimal_places=2, min_value=Decimal("0.01"), **kwargs)


class FormulaireCompte(FormulaireDeFoyer):
    ouvert_le = ChampDate(
        label=_("Date du solde initial"),
        initial=date.today,
        help_text=_("Les opérations saisies doivent être postérieures à cette date."),
    )

    class Meta:
        model = Compte
        fields = (
            "nom",
            "type",
            "etablissement",
            "titulaires",
            "est_epargne",
            "solde_initial",
            "ouvert_le",
        )
        widgets = {"titulaires": forms.CheckboxSelectMultiple}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        titulaires = self.fields["titulaires"]
        titulaires.queryset = titulaires.queryset.select_related("utilisateur")  # type: ignore[attr-defined]
        titulaires.label_from_instance = lambda adhesion: str(adhesion.utilisateur)  # type: ignore[attr-defined]


class Sens:
    DEPENSE = "depense"
    RECETTE = "recette"
    CHOIX = [(DEPENSE, _("Dépense (sortie d'argent)")), (RECETTE, _("Recette (entrée d'argent)"))]


class FormulaireOperation(FormulaireDeFoyer):
    """Le montant est saisi positif avec un sens ; il est stocké signé."""

    date = ChampDate(label=_("Date"), initial=date.today)
    sens = forms.ChoiceField(label=_("Sens"), choices=Sens.CHOIX, initial=Sens.DEPENSE)
    montant = ChampMontantPositif()

    class Meta:
        model = Operation
        fields = ("compte", "date", "libelle", "sens", "montant", "categorie", "note")
        widgets = {"note": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Les éléments archivés ne sont plus proposés, sauf celui déjà utilisé par l'opération.
        comptes = self.fields["compte"]
        comptes.queryset = comptes.queryset.filter(  # type: ignore[attr-defined]
            Q(archive_le__isnull=True) | Q(pk=self.instance.compte_id)
        )
        categories = self.fields["categorie"]
        categories.queryset = (  # type: ignore[attr-defined]
            categories.queryset.filter(parent__isnull=False)  # type: ignore[attr-defined]
            .filter(Q(archive_le__isnull=True) | Q(pk=self.instance.categorie_id))
            .select_related("parent")
            .order_by("parent__nom", "nom")
        )
        if self.instance.pk:
            self.initial["montant"] = abs(self.instance.montant)
            self.initial["sens"] = Sens.RECETTE if self.instance.montant > 0 else Sens.DEPENSE

    def clean(self) -> dict[str, Any]:
        donnees = super().clean() or {}
        montant = donnees.get("montant")
        if montant is not None:
            donnees["montant"] = -montant if donnees.get("sens") == Sens.DEPENSE else montant
        compte, jour = donnees.get("compte"), donnees.get("date")
        if compte and jour and jour < compte.ouvert_le:
            self.add_error(
                "date", _("Cette date est antérieure à celle du solde initial du compte.")
            )
        return donnees


class FormulaireVirement(forms.Form):
    source = forms.ModelChoiceField(label=_("Depuis"), queryset=Compte.objects.none())
    destination = forms.ModelChoiceField(label=_("Vers"), queryset=Compte.objects.none())
    date = ChampDate(label=_("Date"), initial=date.today)
    montant = ChampMontantPositif()
    libelle = forms.CharField(label=_("Libellé"), max_length=200, initial=_("Virement interne"))

    def __init__(self, *args: Any, foyer: Foyer, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        comptes = Compte.objects.du_foyer(foyer).actifs()
        self.fields["source"].queryset = comptes  # type: ignore[attr-defined]
        self.fields["destination"].queryset = comptes  # type: ignore[attr-defined]

    def clean(self) -> dict[str, Any]:
        donnees = super().clean() or {}
        source, destination = donnees.get("source"), donnees.get("destination")
        if source and destination and source == destination:
            self.add_error("destination", _("Choisissez un compte différent du compte source."))
        return donnees


class FormulaireCategorie(FormulaireDeFoyer):
    class Meta:
        model = Categorie
        fields = ("nom", "parent", "nature")
        help_texts = {
            "parent": _("Laissez vide pour créer une catégorie parente."),
            "nature": _("Une sous-catégorie reprend toujours la nature de sa parente."),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        parents = self.fields["parent"]
        parents.queryset = (  # type: ignore[attr-defined]
            parents.queryset.filter(parent__isnull=True)  # type: ignore[attr-defined]
            .filter(Q(archive_le__isnull=True) | Q(pk=self.instance.parent_id))
            .exclude(pk=self.instance.pk)
        )


class FormulaireReleve(forms.Form):
    date = ChampDate(label=_("Date"), initial=date.today)
    montant = forms.DecimalField(label=_("Valeur du compte"), max_digits=12, decimal_places=2)


class FormulaireFiltreOperations(forms.Form):
    compte = forms.ModelChoiceField(
        label=_("Compte"),
        queryset=Compte.objects.none(),
        required=False,
        empty_label=_("Tous les comptes"),
    )
    mois = forms.RegexField(
        label=_("Mois"),
        regex=r"^\d{4}-(0[1-9]|1[0-2])$",
        required=False,
        widget=forms.TextInput(attrs={"type": "month"}),
    )

    def __init__(self, *args: Any, foyer: Foyer, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["compte"].queryset = Compte.objects.du_foyer(foyer)  # type: ignore[attr-defined]
