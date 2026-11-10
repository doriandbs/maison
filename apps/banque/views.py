from datetime import date
from typing import Any

from django.contrib import messages
from django.db.models import Prefetch
from django.forms import ModelForm
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views import View
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    FormView,
    ListView,
    TemplateView,
    UpdateView,
)

from apps.foyers.acces import AccesFoyerMixin, VueDeFoyerMixin, VueFormulaireDeFoyerMixin
from apps.socle.models import RequeteDeFoyer

from .forms import (
    FormulaireCategorie,
    FormulaireCompte,
    FormulaireFiltreOperations,
    FormulaireOperation,
    FormulaireReleve,
    FormulaireVirement,
)
from .models import Categorie, Compte, Operation, ReleveSolde
from .services import categories as service_categories
from .services import operations as service_operations
from .services import soldes as service_soldes


class PageFormulaireMixin:
    """Gabarit commun à tous les écrans de saisie : un titre, un formulaire, un retour."""

    titre: Any = ""
    url_retour: Any = ""

    def get_template_names(self) -> list[str]:
        return ["composants/page_formulaire.html"]

    def get_success_url(self) -> str:
        return str(self.url_retour)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexte = super().get_context_data(**kwargs)  # type: ignore[misc]
        contexte["titre"] = self.titre
        contexte["url_retour"] = self.get_success_url()
        return contexte


# --- Comptes ---------------------------------------------------------------


class VueComptes(AccesFoyerMixin, TemplateView):
    template_name = "banque/comptes.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexte = super().get_context_data(**kwargs)
        soldes = service_soldes.soldes_des_comptes(self.foyer)
        comptes = list(Compte.objects.du_foyer(self.foyer))
        for compte in comptes:
            compte.solde = soldes[compte.pk]  # type: ignore[attr-defined]
        actifs = [compte for compte in comptes if not compte.est_archive]
        contexte["comptes"] = actifs
        contexte["comptes_archives"] = [compte for compte in comptes if compte.est_archive]
        contexte["total"] = sum(compte.solde for compte in actifs)  # type: ignore[attr-defined]
        return contexte


class VueCompte(VueDeFoyerMixin, DetailView):
    model = Compte
    template_name = "banque/compte.html"
    context_object_name = "compte"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexte = super().get_context_data(**kwargs)
        compte: Compte = self.object
        contexte["solde"] = service_soldes.soldes_des_comptes(self.foyer)[compte.pk]
        contexte["operations"] = compte.operations.select_related("categorie__parent")[:10]
        if compte.est_valorise:
            contexte["releves"] = compte.releves.all()[:24]
            contexte["formulaire_releve"] = FormulaireReleve()
        return contexte


class VueAjouterCompte(PageFormulaireMixin, VueFormulaireDeFoyerMixin, VueDeFoyerMixin, CreateView):
    model = Compte
    form_class = FormulaireCompte
    titre = gettext_lazy("Ajouter un compte")
    url_retour = reverse_lazy("banque:comptes")


class VueModifierCompte(
    PageFormulaireMixin, VueFormulaireDeFoyerMixin, VueDeFoyerMixin, UpdateView
):
    model = Compte
    form_class = FormulaireCompte
    titre = gettext_lazy("Modifier le compte")
    url_retour = reverse_lazy("banque:comptes")


class VueArchiverCompte(AccesFoyerMixin, View):
    """Archive ou désarchive : l'historique des opérations est toujours conservé."""

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        compte = get_object_or_404(Compte.objects.du_foyer(self.foyer), pk=pk)
        compte.archive_le = None if compte.est_archive else timezone.now()
        compte.save(update_fields=["archive_le", "modifie_le"])
        return redirect("banque:comptes")


class VueAjouterReleve(AccesFoyerMixin, View):
    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        compte = get_object_or_404(Compte.objects.du_foyer(self.foyer), pk=pk)
        formulaire = FormulaireReleve(request.POST)
        if formulaire.is_valid():
            service_soldes.enregistrer_releve(
                compte=compte,
                date_releve=formulaire.cleaned_data["date"],
                montant=formulaire.cleaned_data["montant"],
            )
            messages.success(request, _("Relevé enregistré."))
        else:
            messages.error(request, _("Date ou montant invalide."))
        return redirect("banque:compte", pk=compte.pk)


class VueSupprimerReleve(AccesFoyerMixin, View):
    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        releve = get_object_or_404(ReleveSolde.objects.du_foyer(self.foyer), pk=pk)
        releve.delete()
        return redirect("banque:compte", pk=releve.compte_id)


# --- Opérations ------------------------------------------------------------


class VueOperations(VueDeFoyerMixin, ListView):
    model = Operation
    template_name = "banque/operations.html"
    context_object_name = "operations"
    paginate_by = 50

    def get_queryset(self) -> RequeteDeFoyer:
        operations = super().get_queryset().select_related("compte", "categorie__parent")
        self.filtre = FormulaireFiltreOperations(self.request.GET or None, foyer=self.foyer)
        if self.filtre.is_valid():
            if compte := self.filtre.cleaned_data["compte"]:
                operations = operations.filter(compte=compte)
            if mois := self.filtre.cleaned_data["mois"]:
                annee, numero = mois.split("-")
                operations = operations.filter(date__year=annee, date__month=numero)
        return operations

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexte = super().get_context_data(**kwargs)
        contexte["filtre"] = self.filtre
        parametres = self.request.GET.copy()
        parametres.pop("page", None)
        contexte["parametres"] = parametres.urlencode()
        return contexte


class VueAjouterOperation(
    PageFormulaireMixin, VueFormulaireDeFoyerMixin, VueDeFoyerMixin, CreateView
):
    model = Operation
    form_class = FormulaireOperation
    titre = gettext_lazy("Ajouter une opération")
    url_retour = reverse_lazy("banque:operations")

    def get_initial(self) -> dict[str, Any]:
        return {"compte": self.request.GET.get("compte"), "date": date.today()}

    def form_valid(self, form: ModelForm) -> HttpResponse:
        form.instance.cree_par = self.request.user
        return super().form_valid(form)


class VueModifierOperation(
    PageFormulaireMixin, VueFormulaireDeFoyerMixin, VueDeFoyerMixin, UpdateView
):
    model = Operation
    form_class = FormulaireOperation
    titre = gettext_lazy("Modifier l'opération")
    url_retour = reverse_lazy("banque:operations")

    def get_queryset(self) -> RequeteDeFoyer:
        # Un virement ne se modifie pas jambe par jambe : on le supprime et on le recrée.
        return super().get_queryset().filter(groupe_virement__isnull=True)


class VueSupprimerOperation(VueDeFoyerMixin, DeleteView):
    model = Operation
    template_name = "composants/page_confirmation.html"
    success_url = reverse_lazy("banque:operations")

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexte = super().get_context_data(**kwargs)
        contexte["titre"] = _("Supprimer l'opération")
        contexte["url_retour"] = self.success_url
        contexte["question"] = (
            _("Ce virement sera supprimé sur les deux comptes concernés.")
            if self.object.est_virement
            else _("Cette opération sera définitivement supprimée.")
        )
        return contexte

    def form_valid(self, form: Any) -> HttpResponse:
        service_operations.supprimer_operation(self.object)
        return redirect(self.success_url)


class VueAjouterVirement(PageFormulaireMixin, VueFormulaireDeFoyerMixin, FormView):
    form_class = FormulaireVirement
    titre = gettext_lazy("Ajouter un virement interne")
    url_retour = reverse_lazy("banque:operations")

    def form_valid(self, form: FormulaireVirement) -> HttpResponse:
        donnees = form.cleaned_data
        service_operations.creer_virement(
            source=donnees["source"],
            destination=donnees["destination"],
            date_virement=donnees["date"],
            montant=donnees["montant"],
            libelle=donnees["libelle"],
            cree_par=self.request.user,  # type: ignore[arg-type]
        )
        return super().form_valid(form)


# --- Catégories ------------------------------------------------------------


class VueCategories(AccesFoyerMixin, TemplateView):
    template_name = "banque/categories.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexte = super().get_context_data(**kwargs)
        categories = Categorie.objects.du_foyer(self.foyer)
        contexte["categories"] = (
            categories.filter(parent__isnull=True)
            .prefetch_related(Prefetch("sous_categories", queryset=categories.order_by("nom")))
            .order_by("-nature", "nom")
        )
        return contexte


class VueAjouterCategorie(
    PageFormulaireMixin, VueFormulaireDeFoyerMixin, VueDeFoyerMixin, CreateView
):
    model = Categorie
    form_class = FormulaireCategorie
    titre = gettext_lazy("Ajouter une catégorie")
    url_retour = reverse_lazy("banque:categories")

    def get_initial(self) -> dict[str, Any]:
        return {"parent": self.request.GET.get("parent")}


class VueModifierCategorie(
    PageFormulaireMixin, VueFormulaireDeFoyerMixin, VueDeFoyerMixin, UpdateView
):
    model = Categorie
    form_class = FormulaireCategorie
    titre = gettext_lazy("Modifier la catégorie")
    url_retour = reverse_lazy("banque:categories")


class VueArchiverCategorie(AccesFoyerMixin, View):
    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        categorie = get_object_or_404(Categorie.objects.du_foyer(self.foyer), pk=pk)
        service_categories.basculer_archivage_categorie(categorie)
        return redirect(reverse("banque:categories"))
