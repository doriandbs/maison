from datetime import date
from typing import Any

from django.contrib import messages
from django.db.models import Prefetch, Q
from django.forms import ModelForm
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, ngettext
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
from apps.foyers.middleware import CLE_SESSION_FOYER
from apps.foyers.models import Role
from apps.socle.limites import limiter_par_utilisateur
from apps.socle.models import RequeteDeFoyer
from apps.socle.views import PageFormulaireMixin

from .forms import (
    FormulaireApercu,
    FormulaireCategorie,
    FormulaireCompte,
    FormulaireFiltreOperations,
    FormulaireImport,
    FormulaireOperation,
    FormulaireRegle,
    FormulaireReleve,
    FormulaireTransfert,
    FormulaireVirement,
)
from .importation import ErreurImport, depuis_session, lire_releve, vers_session
from .models import Categorie, Compte, Operation, RegleCategorisation, ReleveSolde
from .services import categories as service_categories
from .services import importation as service_importation
from .services import operations as service_operations
from .services import regles as service_regles
from .services import soldes as service_soldes
from .services import transfert as service_transfert
from .services.regroupement import regrouper_par_etablissement

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
        contexte["groupes"] = regrouper_par_etablissement(actifs, soldes)
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
        operations = (
            super()
            .get_queryset()
            .select_related("compte", "categorie__parent")
            .prefetch_related("documents")
        )
        self.filtre = FormulaireFiltreOperations(self.request.GET or None, foyer=self.foyer)
        if self.filtre.is_valid():
            if recherche := self.filtre.cleaned_data["recherche"]:
                operations = operations.filter(
                    Q(libelle__icontains=recherche)
                    | Q(libelle_banque__icontains=recherche)
                    | Q(note__icontains=recherche)
                )
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


# --- Import de relevés -------------------------------------------------------

CLE_SESSION_IMPORT = "import_releve"


@limiter_par_utilisateur("30/h")
class VueImporter(PageFormulaireMixin, VueFormulaireDeFoyerMixin, FormView):
    form_class = FormulaireImport
    titre = gettext_lazy("Importer un relevé")
    url_retour = reverse_lazy("banque:operations")

    def get_initial(self) -> dict[str, Any]:
        return {"compte": self.request.GET.get("compte")}

    def form_valid(self, form: FormulaireImport) -> HttpResponse:
        try:
            releve = lire_releve(form.cleaned_data["fichier"].read())
        except ErreurImport as erreur:
            form.add_error("fichier", str(erreur))
            return self.form_invalid(form)
        # Gardé côté serveur (session en base) : le navigateur ne peut pas le modifier.
        self.request.session[CLE_SESSION_IMPORT] = {
            "foyer": self.foyer.pk,
            "compte": form.cleaned_data["compte"].pk,
            "releve": vers_session(releve),
        }
        return redirect("banque:apercu_import")


class VueApercuImport(AccesFoyerMixin, View):
    """Vérification ligne à ligne avant l'enregistrement ; recalculée à chaque affichage."""

    def _apercu(self) -> service_importation.Apercu | None:
        donnees = self.request.session.get(CLE_SESSION_IMPORT)
        if not donnees or donnees["foyer"] != self.foyer.pk:
            return None
        compte = get_object_or_404(Compte.objects.du_foyer(self.foyer), pk=donnees["compte"])
        return service_importation.preparer(compte, depuis_session(donnees["releve"]))

    def _afficher(self, formulaire: FormulaireApercu) -> HttpResponse:
        apercu = formulaire.apercu
        Statut = service_importation.Statut
        contexte = {
            "apercu": apercu,
            "formulaire": formulaire,
            "nb_nouvelles": apercu.compter(Statut.NOUVELLE),
            "nb_doublons": apercu.compter(Statut.DOUBLON_POSSIBLE),
            "nb_deja": apercu.compter(Statut.DEJA_IMPORTEE),
            "nb_anterieures": apercu.compter(Statut.ANTERIEURE),
        }
        return render(self.request, "banque/apercu_import.html", contexte)

    def get(self, request: HttpRequest) -> HttpResponse:
        apercu = self._apercu()
        if apercu is None:
            return redirect("banque:importer")
        return self._afficher(FormulaireApercu(apercu=apercu, foyer=self.foyer))

    def post(self, request: HttpRequest) -> HttpResponse:
        apercu = self._apercu()
        if apercu is None:
            return redirect("banque:importer")
        action = request.POST.get("action")
        if action == "annuler":
            request.session.pop(CLE_SESSION_IMPORT, None)
            return redirect("banque:operations")
        if action == "avancer_debut":
            service_importation.avancer_le_debut(apercu)
            messages.success(
                request, _("Date de départ du compte avancée ; le solde actuel est inchangé.")
            )
            return redirect("banque:apercu_import")

        formulaire = FormulaireApercu(request.POST, apercu=apercu, foyer=self.foyer)
        if not formulaire.is_valid():
            return self._afficher(formulaire)
        retenues = formulaire.retenues()
        for ligne, categorie, memoriser in retenues:
            if memoriser and categorie is not None:
                service_regles.memoriser(self.foyer, ligne.tiers, categorie)
        nombre = service_importation.enregistrer(
            apercu.compte,
            [service_importation.Choix(ligne, categorie) for ligne, categorie, _m in retenues],
            cree_par=request.user,  # type: ignore[arg-type]
        )
        request.session.pop(CLE_SESSION_IMPORT, None)
        messages.success(
            request,
            ngettext("%(n)d opération importée.", "%(n)d opérations importées.", nombre)
            % {"n": nombre},
        )
        return redirect(f"{reverse('banque:operations')}?compte={apercu.compte.pk}")


# --- Règles de catégorisation ------------------------------------------------


class VueRegles(VueFormulaireDeFoyerMixin, CreateView):
    model = RegleCategorisation
    form_class = FormulaireRegle
    template_name = "banque/regles.html"
    success_url = reverse_lazy("banque:regles")

    def get_initial(self) -> dict[str, Any]:
        return {"motif": self.request.GET.get("motif", "")}

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexte = super().get_context_data(**kwargs)
        contexte["regles"] = RegleCategorisation.objects.du_foyer(self.foyer).select_related(
            "categorie__parent"
        )
        contexte["a_classer"] = (
            Operation.objects.du_foyer(self.foyer)
            .filter(categorie__isnull=True, groupe_virement__isnull=True)
            .count()
        )
        return contexte

    def form_valid(self, form: ModelForm) -> HttpResponse:
        messages.success(self.request, _("Règle ajoutée."))
        return super().form_valid(form)


class VueSupprimerRegle(AccesFoyerMixin, View):
    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        get_object_or_404(RegleCategorisation.objects.du_foyer(self.foyer), pk=pk).delete()
        return redirect("banque:regles")


class VueAppliquerRegles(AccesFoyerMixin, View):
    def post(self, request: HttpRequest) -> HttpResponse:
        nombre = service_regles.appliquer_aux_operations_a_classer(self.foyer)
        messages.success(
            request,
            ngettext("%(n)d opération classée.", "%(n)d opérations classées.", nombre)
            % {"n": nombre},
        )
        return redirect("banque:regles")


# --- Déplacer des comptes vers un autre foyer --------------------------------


class VueTransfererComptes(AccesFoyerMixin, FormView):
    """Aperçu de ce qui va être déplacé, puis déplacement sur confirmation."""

    # Retirer un compte d'un foyer touche tous ses membres : réservé aux administrateurs.
    role_lecture = Role.ADMINISTRATEUR
    role_ecriture = Role.ADMINISTRATEUR
    template_name = "banque/transfert.html"
    form_class = FormulaireTransfert

    def get_form_kwargs(self) -> dict[str, Any]:
        arguments = super().get_form_kwargs()
        arguments["foyer"] = self.foyer
        arguments["adhesions"] = self.request.adhesions  # type: ignore[attr-defined]
        return arguments

    def get_initial(self) -> dict[str, Any]:
        return {"comptes": self.request.GET.getlist("compte")}

    def form_valid(self, form: FormulaireTransfert) -> HttpResponse:
        comptes = list(form.cleaned_data["comptes"])
        destination = form.cleaned_data["destination"]
        if "confirmer" not in self.request.POST:
            bilan = service_transfert.preparer(comptes, self.foyer, destination)
            return self.render_to_response(self.get_context_data(form=form, bilan=bilan))
        bilan = service_transfert.transferer(
            comptes, self.foyer, destination, copier_regles=form.cleaned_data["copier_regles"]
        )
        # On suit les comptes : le foyer d'arrivée devient le foyer courant.
        self.request.session[CLE_SESSION_FOYER] = destination.pk
        messages.success(
            self.request,
            ngettext(
                "%(n)d compte déplacé vers « %(foyer)s ».",
                "%(n)d comptes déplacés vers « %(foyer)s ».",
                len(bilan.comptes),
            )
            % {"n": len(bilan.comptes), "foyer": destination.nom},
        )
        return redirect("banque:comptes")
