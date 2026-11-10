from datetime import date
from typing import Any

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, TemplateView, UpdateView

from apps.foyers.acces import AccesFoyerMixin, VueDeFoyerMixin, VueFormulaireDeFoyerMixin
from apps.socle.views import PageFormulaireMixin

from .forms import FormulaireAnticipe, FormulairePret, FormulaireSimulation
from .models import Pret, RemboursementAnticipe
from .services import encours as service_encours
from .services.amortissement import Anticipe, simuler


class VuePrets(AccesFoyerMixin, TemplateView):
    template_name = "prets/liste.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexte = super().get_context_data(**kwargs)
        encours = service_encours.encours_du_foyer(self.foyer, date.today())
        contexte["encours"] = [e for e in encours if not e.est_termine]
        contexte["termines"] = [e for e in encours if e.est_termine]
        contexte["total_du"] = service_encours.total_dettes(encours)
        contexte["total_mensualites"] = sum(
            (e.prochaine_echeance.total for e in encours if e.prochaine_echeance), 0
        )
        return contexte


class VuePret(VueDeFoyerMixin, DetailView):
    model = Pret
    template_name = "prets/pret.html"
    context_object_name = "pret"

    def get_queryset(self) -> Any:
        return super().get_queryset().select_related("compte").prefetch_related("remboursements")

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexte = super().get_context_data(**kwargs)
        pret: Pret = self.object
        aujourd_hui = date.today()
        tableau = pret.tableau()
        contexte["encours"] = service_encours.Encours(pret, tableau, aujourd_hui)
        contexte["tableau"] = tableau
        contexte["annees"] = service_encours.par_annee(tableau, aujourd_hui)
        contexte["formulaire_anticipe"] = FormulaireAnticipe(foyer=self.foyer)

        # La simulation passe par GET : rien n'est enregistré, l'adresse se partage.
        formulaire = FormulaireSimulation(
            self.request.GET if "montant" in self.request.GET else None
        )
        contexte["formulaire_simulation"] = formulaire
        if formulaire.is_valid():
            donnees = formulaire.cleaned_data
            contexte["simulation"] = simuler(
                pret.conditions,
                pret.anticipes(),
                Anticipe(donnees["date"], donnees["montant"], donnees["effet"]),
            )
        return contexte


class VueAjouterPret(PageFormulaireMixin, VueFormulaireDeFoyerMixin, VueDeFoyerMixin, CreateView):
    model = Pret
    form_class = FormulairePret
    titre = gettext_lazy("Ajouter un crédit")
    url_retour = reverse_lazy("prets:liste")

    def get_success_url(self) -> str:
        pret = getattr(self, "object", None)
        return reverse("prets:pret", args=[pret.pk]) if pret else str(self.url_retour)


class VueModifierPret(PageFormulaireMixin, VueFormulaireDeFoyerMixin, VueDeFoyerMixin, UpdateView):
    model = Pret
    form_class = FormulairePret
    titre = gettext_lazy("Modifier le crédit")

    def get_success_url(self) -> str:
        return reverse("prets:pret", args=[self.object.pk])


class VueSupprimerPret(VueDeFoyerMixin, DeleteView):
    model = Pret
    template_name = "composants/page_confirmation.html"
    success_url = reverse_lazy("prets:liste")

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexte = super().get_context_data(**kwargs)
        contexte["titre"] = _("Supprimer le crédit")
        contexte["url_retour"] = reverse("prets:pret", args=[self.object.pk])
        contexte["question"] = _(
            "Le crédit et ses remboursements anticipés seront supprimés. "
            "Les opérations bancaires ne sont pas touchées."
        )
        return contexte


class VueAjouterAnticipe(AccesFoyerMixin, View):
    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        pret = get_object_or_404(Pret.objects.du_foyer(self.foyer), pk=pk)
        formulaire = FormulaireAnticipe(request.POST, foyer=self.foyer)
        if formulaire.is_valid():
            remboursement = formulaire.save(commit=False)
            remboursement.pret = pret
            remboursement.save()
            messages.success(request, _("Remboursement anticipé enregistré."))
        else:
            messages.error(request, _("Date ou montant invalide."))
        return redirect("prets:pret", pk=pret.pk)


class VueSupprimerAnticipe(AccesFoyerMixin, View):
    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        remboursement = get_object_or_404(RemboursementAnticipe.objects.du_foyer(self.foyer), pk=pk)
        remboursement.delete()
        return redirect("prets:pret", pk=remboursement.pret_id)
