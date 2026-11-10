from datetime import date
from decimal import Decimal
from typing import Any

from django import forms
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.banque.forms import ChampDate
from apps.socle.forms import FormulaireDeFoyer

from .models import EffetAnticipe, Pret, RemboursementAnticipe


class FormulairePret(FormulaireDeFoyer):
    premiere_echeance = ChampDate(label=_("Date de la première échéance"))

    class Meta:
        model = Pret
        fields = (
            "nom",
            "etablissement",
            "capital",
            "taux_annuel",
            "duree_mois",
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
