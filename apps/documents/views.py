from datetime import date
from typing import Any

from django.db.models import Q
from django.http import FileResponse, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from apps.foyers.acces import AccesFoyerMixin, VueDeFoyerMixin, VueFormulaireDeFoyerMixin
from apps.socle.models import RequeteDeFoyer
from apps.socle.views import PageFormulaireMixin

from . import services
from .forms import FormulaireDocument, FormulaireFiltreDocuments
from .models import Document, TypeDocument


class VueDocuments(VueDeFoyerMixin, ListView):
    portee = "foyer"
    model = Document
    template_name = "documents/liste.html"
    context_object_name = "documents"
    paginate_by = 50

    def get_queryset(self) -> RequeteDeFoyer:
        documents = super().get_queryset().select_related("categorie__parent")
        self.filtre = FormulaireFiltreDocuments(self.request.GET or None)
        if self.filtre.is_valid():
            if recherche := self.filtre.cleaned_data["recherche"]:
                documents = documents.filter(
                    Q(titre__icontains=recherche) | Q(emetteur__icontains=recherche)
                )
            if type_document := self.filtre.cleaned_data["type"]:
                documents = documents.filter(type=type_document)
            if self.filtre.cleaned_data["a_payer"]:
                documents = documents.a_payer()  # type: ignore[attr-defined]
        return documents

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexte = super().get_context_data(**kwargs)
        contexte["filtre"] = self.filtre
        parametres = self.request.GET.copy()
        parametres.pop("page", None)
        contexte["parametres"] = parametres.urlencode()
        return contexte


class VueDocument(VueDeFoyerMixin, DetailView):
    portee = "foyer"
    model = Document
    template_name = "documents/document.html"
    context_object_name = "document"

    def get_queryset(self) -> RequeteDeFoyer:
        return super().get_queryset().select_related("categorie__parent", "compte", "operation")


class VueAjouterDocument(
    PageFormulaireMixin, VueFormulaireDeFoyerMixin, VueDeFoyerMixin, CreateView
):
    portee = "foyer"
    model = Document
    form_class = FormulaireDocument
    titre = gettext_lazy("Ajouter un document")
    url_retour = reverse_lazy("documents:liste")

    def get_initial(self) -> dict[str, Any]:
        return {"date": date.today()}

    def form_valid(self, form: FormulaireDocument) -> HttpResponse:  # type: ignore[override]
        form.instance.cree_par = self.request.user
        return super().form_valid(form)

    def get_success_url(self) -> str:
        # Après l'enregistrement, on ouvre le document ; avant, c'est le lien « Annuler ».
        document = getattr(self, "object", None)
        if document is not None:
            return reverse("documents:document", args=[document.pk])
        return str(self.url_retour)


class VueModifierDocument(
    PageFormulaireMixin, VueFormulaireDeFoyerMixin, VueDeFoyerMixin, UpdateView
):
    portee = "foyer"
    model = Document
    form_class = FormulaireDocument
    titre = gettext_lazy("Modifier le document")

    def get_success_url(self) -> str:
        return reverse("documents:document", args=[self.object.pk])


class VueSupprimerDocument(VueDeFoyerMixin, DeleteView):
    portee = "foyer"
    model = Document
    template_name = "composants/page_confirmation.html"
    success_url = reverse_lazy("documents:liste")

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexte = super().get_context_data(**kwargs)
        contexte["titre"] = _("Supprimer le document")
        contexte["url_retour"] = reverse("documents:document", args=[self.object.pk])
        contexte["question"] = _("Le document et son fichier seront définitivement supprimés.")
        return contexte

    def form_valid(self, form: Any) -> HttpResponse:
        services.supprimer_document(self.object)
        return redirect(self.success_url)


class VueBasculerPaiement(AccesFoyerMixin, View):
    portee = "foyer"
    """Bascule une facture entre « payée aujourd'hui » et « à payer »."""

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        factures = Document.objects.du_foyer(self.foyer).filter(type=TypeDocument.FACTURE)
        facture = get_object_or_404(factures, pk=pk)
        facture.paye_le = None if facture.paye_le else date.today()
        facture.save(update_fields=["paye_le", "modifie_le"])
        retour = request.POST.get("retour", "")
        if url_has_allowed_host_and_scheme(retour, allowed_hosts={request.get_host()}):
            return redirect(retour)
        return redirect("documents:document", pk=facture.pk)


class VueFichierDocument(AccesFoyerMixin, View):
    portee = "foyer"
    """Seul chemin d'accès aux fichiers : droits vérifiés, puis envoi par Django.

    Le type envoyé est celui détecté au dépôt, jamais celui annoncé par le navigateur.
    La CSP « sandbox » neutralise tout script qu'un fichier piégé tenterait d'exécuter.
    """

    def get(self, request: HttpRequest, pk: int) -> FileResponse:
        document = get_object_or_404(Document.objects.du_foyer(self.foyer), pk=pk)
        reponse = FileResponse(
            document.fichier.open("rb"),
            as_attachment="telecharger" in request.GET,
            filename=document.nom_fichier,
            content_type=document.type_mime,
        )
        reponse["Content-Security-Policy"] = "sandbox; default-src 'none'; img-src 'self'"
        reponse["X-Content-Type-Options"] = "nosniff"
        reponse["Cache-Control"] = "private, no-store"
        return reponse
