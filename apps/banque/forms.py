from datetime import date
from decimal import Decimal
from typing import Any

from django import forms
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.foyers.models import Foyer
from apps.socle.forms import FormulaireDeFoyer

from .models import Categorie, Compte, Operation, RegleCategorisation


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
    recherche = forms.CharField(
        label=_("Rechercher"),
        required=False,
        max_length=100,
        widget=forms.TextInput(attrs={"type": "search", "placeholder": _("Libellé, note…")}),
    )
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


# --- Import de relevés et règles ---------------------------------------------


def sous_categories_proposees(foyer: Foyer) -> Any:
    return (
        Categorie.objects.du_foyer(foyer)
        .filter(parent__isnull=False, archive_le__isnull=True)
        .select_related("parent")
        .order_by("parent__nom", "nom")
    )


class FormulaireImport(forms.Form):
    compte = forms.ModelChoiceField(label=_("Compte"), queryset=Compte.objects.none())
    fichier = forms.FileField(
        label=_("Relevé"),
        help_text=_(
            "Société Générale : espace client → le compte → « Télécharger » → format CSV. "
            "Vous pourrez vérifier chaque ligne avant l'import."
        ),
        widget=forms.ClearableFileInput(attrs={"accept": ".csv,text/csv"}),
    )

    def __init__(self, *args: Any, foyer: Foyer, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["compte"].queryset = Compte.objects.du_foyer(foyer).actifs()  # type: ignore[attr-defined]


class FormulaireApercu(forms.Form):
    """Une case « importer », une catégorie et une case « mémoriser » par ligne importable."""

    def __init__(self, *args: Any, apercu: Any, foyer: Foyer, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.apercu = apercu
        categories = sous_categories_proposees(foyer)
        for ligne in apercu.lignes:
            if not ligne.importable:
                continue
            self.fields[f"inclure_{ligne.rang}"] = forms.BooleanField(
                required=False, initial=ligne.cochee_par_defaut, label=_("Importer")
            )
            self.fields[f"categorie_{ligne.rang}"] = forms.ModelChoiceField(
                queryset=categories,
                required=False,
                initial=ligne.categorie,
                empty_label=_("À classer"),
                label=_("Catégorie"),
            )
            self.fields[f"memoriser_{ligne.rang}"] = forms.BooleanField(
                required=False, label=_("Toujours classer ainsi")
            )

    def lignes(self) -> list[dict[str, Any]]:
        """Lignes de l'aperçu avec leurs champs, pour le gabarit (sans logique de rendu)."""
        return [
            {
                "ligne": ligne,
                "inclure": self[f"inclure_{ligne.rang}"] if ligne.importable else None,
                "categorie": self[f"categorie_{ligne.rang}"] if ligne.importable else None,
                "memoriser": self[f"memoriser_{ligne.rang}"] if ligne.importable else None,
            }
            for ligne in self.apercu.lignes
        ]

    def retenues(self) -> list[tuple[Any, Categorie | None, bool]]:
        """(ligne, catégorie choisie, règle à mémoriser) pour chaque ligne cochée."""
        donnees = self.cleaned_data
        return [
            (ligne, donnees[f"categorie_{ligne.rang}"], donnees[f"memoriser_{ligne.rang}"])
            for ligne in self.apercu.lignes
            if ligne.importable and donnees.get(f"inclure_{ligne.rang}")
        ]


class FormulaireRegle(FormulaireDeFoyer):
    class Meta:
        model = RegleCategorisation
        fields = ("motif", "categorie")

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["categorie"].queryset = sous_categories_proposees(self.foyer)  # type: ignore[attr-defined]

    def clean_motif(self) -> str:
        motif = " ".join(self.cleaned_data["motif"].split())
        if len(motif) < 2:
            raise forms.ValidationError(_("Au moins 2 caractères."))
        # Django ne vérifie pas seul cette contrainte : le foyer n'est pas un champ du formulaire.
        doublon = (
            RegleCategorisation.objects.du_foyer(self.foyer)
            .filter(motif__iexact=motif)
            .exclude(pk=self.instance.pk)
        )
        if doublon.exists():
            raise forms.ValidationError(_("Une règle existe déjà pour ce motif."))
        return motif


class FormulaireTransfert(forms.Form):
    destination = forms.ModelChoiceField(label=_("Vers le foyer"), queryset=Foyer.objects.none())
    comptes = forms.ModelMultipleChoiceField(
        label=_("Comptes à déplacer"),
        queryset=Compte.objects.none(),
        widget=forms.CheckboxSelectMultiple,
    )
    copier_regles = forms.BooleanField(
        label=_("Recopier aussi les règles de catégorisation automatique"),
        required=False,
        initial=True,
    )

    def __init__(self, *args: Any, foyer: Foyer, adhesions: list[Any], **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        from apps.foyers.models import Role

        # Seuls les foyers où l'utilisateur peut écrire, jamais celui d'un autre.
        possibles = [
            a.foyer_id for a in adhesions if a.foyer_id != foyer.pk and a.a_au_moins(Role.MEMBRE)
        ]
        self.fields["destination"].queryset = Foyer.objects.filter(pk__in=possibles)  # type: ignore[attr-defined]
        self.fields["comptes"].queryset = Compte.objects.du_foyer(foyer)  # type: ignore[attr-defined]
