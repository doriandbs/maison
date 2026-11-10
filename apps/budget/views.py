from datetime import date
from typing import Any

from django.contrib import messages
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.utils.functional import cached_property
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import FormView, TemplateView

from apps.banque.models import Categorie, Nature
from apps.foyers.acces import AccesFoyerMixin

from .forms import FormulairePrevisionnel
from .services.previsionnel import budgets_du_mois, enregistrer_budgets
from .services.recap import recap_annuel
from .services.tableau import tableau_mensuel

ANNEES_ACCEPTEES = range(2000, 2101)


def _annee_ou_404(annee: int) -> int:
    if annee not in ANNEES_ACCEPTEES:
        raise Http404
    return annee


def _mois_ou_404(annee: int, mois: int) -> date:
    if mois not in range(1, 13):
        raise Http404
    return date(_annee_ou_404(annee), mois, 1)


def _mois_voisin(mois: date, decalage: int) -> date:
    rang = mois.year * 12 + (mois.month - 1) + decalage
    return date(rang // 12, rang % 12 + 1, 1)


class VueBudgetCourant(AccesFoyerMixin, View):
    def get(self, request: HttpRequest) -> HttpResponse:
        aujourd_hui = date.today()
        return redirect("budget:mois", annee=aujourd_hui.year, mois=aujourd_hui.month)


class VueTableauMensuel(AccesFoyerMixin, TemplateView):
    template_name = "budget/tableau.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexte = super().get_context_data(**kwargs)
        mois = _mois_ou_404(kwargs["annee"], kwargs["mois"])
        contexte["tableau"] = tableau_mensuel(self.foyer, mois.year, mois.month)
        contexte["mois_precedent"] = _mois_voisin(mois, -1)
        contexte["mois_suivant"] = _mois_voisin(mois, 1)
        return contexte


class VueRecapAnnuel(AccesFoyerMixin, TemplateView):
    template_name = "budget/recap.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexte = super().get_context_data(**kwargs)
        annee = _annee_ou_404(kwargs["annee"])
        contexte["recap"] = recap_annuel(self.foyer, annee)
        contexte["annee_precedente"] = annee - 1
        contexte["annee_suivante"] = annee + 1
        return contexte


class VuePrevisionnel(AccesFoyerMixin, FormView):
    template_name = "budget/previsionnel.html"
    form_class = FormulairePrevisionnel

    @cached_property
    def mois(self) -> date:
        return _mois_ou_404(self.kwargs["annee"], self.kwargs["mois"])

    def get_form_kwargs(self) -> dict[str, Any]:
        arguments = super().get_form_kwargs()
        arguments["categories"] = list(
            Categorie.objects.du_foyer(self.foyer).actifs().filter(nature=Nature.DEPENSE)
        )
        arguments["budgets"] = budgets_du_mois(self.foyer, self.mois)
        return arguments

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexte = super().get_context_data(**kwargs)
        contexte["mois"] = self.mois
        return contexte

    def form_valid(self, form: FormulairePrevisionnel) -> HttpResponse:
        modifies = enregistrer_budgets(
            foyer=self.foyer,
            mois=self.mois,
            montants=form.montants(),
            ponctuel=form.est_ponctuel,
        )
        messages.success(self.request, _("%(nombre)d budget(s) mis à jour.") % {"nombre": modifies})
        return redirect("budget:mois", annee=self.mois.year, mois=self.mois.month)
