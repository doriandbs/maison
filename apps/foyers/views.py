from typing import Any

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import FormView, TemplateView

from apps.socle.limites import limiter_par_utilisateur

from . import services
from .acces import AccesFoyerMixin
from .forms import FormulaireFoyer, FormulaireInvitation, FormulaireRole, roles_attribuables
from .middleware import CLE_SESSION_ESPACE, CLE_SESSION_FOYER
from .models import Adhesion, Invitation, Role


class VueMesFoyers(LoginRequiredMixin, TemplateView):
    # Les invitations reçues n'y sont pas listées : un compte peut être créé avec n'importe
    # quelle adresse sans la confirmer, seul le lien envoyé par e-mail prouve qu'elle est à soi.
    template_name = "foyers/liste.html"


class VueCreerFoyer(LoginRequiredMixin, FormView):
    template_name = "foyers/creer.html"
    form_class = FormulaireFoyer

    def form_valid(self, form: FormulaireFoyer) -> HttpResponse:
        foyer = services.creer_foyer(
            utilisateur=self.request.user,  # type: ignore[arg-type]
            nom=form.cleaned_data["nom"],
        )
        self.request.session[CLE_SESSION_FOYER] = foyer.pk
        messages.success(self.request, _("Le foyer « %(nom)s » est créé.") % {"nom": foyer.nom})
        return redirect("accueil")


class VueActiverFoyer(LoginRequiredMixin, View):
    """Change le foyer partagé courant de la session (jamais un espace personnel)."""

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        adhesion = get_object_or_404(
            Adhesion, utilisateur=request.user, foyer_id=pk, foyer__personne__isnull=True
        )
        request.session[CLE_SESSION_FOYER] = adhesion.foyer_id
        return redirect("accueil")


class VueChoisirEspace(LoginRequiredMixin, View):
    """Affiche les finances d'une personne : soi, ou un membre du foyer courant."""

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        espaces = getattr(request, "espaces", [])
        if not any(acces.foyer_id == pk for acces in espaces):
            raise Http404
        request.session[CLE_SESSION_ESPACE] = pk
        # Retour possible vers une page de ses finances (ex. un compte cliqué depuis
        # « Comptes de Dorian »), jamais vers un autre site.
        suivante = request.POST.get("next", "")
        if url_has_allowed_host_and_scheme(suivante, allowed_hosts={request.get_host()}):
            return redirect(suivante)
        return redirect("accueil")


class VueFoyerPrincipal(LoginRequiredMixin, View):
    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        adhesion = get_object_or_404(
            Adhesion, utilisateur=request.user, foyer_id=pk, foyer__personne__isnull=True
        )
        services.definir_foyer_principal(adhesion)
        return redirect("foyers:liste")


class VueMembres(AccesFoyerMixin, TemplateView):
    portee = "foyer"
    template_name = "foyers/membres.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexte = super().get_context_data(**kwargs)
        membres = list(
            Adhesion.objects.du_foyer(self.foyer)
            .select_related("utilisateur")
            .order_by("utilisateur__email")
        )
        est_proprietaire = self.adhesion.role == Role.PROPRIETAIRE
        peut_administrer = self.adhesion.a_au_moins(Role.ADMINISTRATEUR)
        for membre in membres:
            # Un administrateur ne touche pas aux propriétaires (le service le refuserait).
            membre.gerable = peut_administrer and (  # type: ignore[attr-defined]
                est_proprietaire or membre.role != Role.PROPRIETAIRE
            )
        contexte["membres"] = membres
        contexte["roles"] = roles_attribuables(self.adhesion)
        if self.adhesion.a_au_moins(Role.ADMINISTRATEUR):
            contexte["invitations"] = Invitation.objects.du_foyer(self.foyer).en_attente()
            contexte["formulaire_invitation"] = FormulaireInvitation(par=self.adhesion)
        return contexte


@limiter_par_utilisateur("20/h")
class VueInviter(AccesFoyerMixin, View):
    portee = "foyer"
    role_ecriture = Role.ADMINISTRATEUR

    def post(self, request: HttpRequest) -> HttpResponse:
        formulaire = FormulaireInvitation(request.POST, par=self.adhesion)
        if not formulaire.is_valid():
            messages.error(request, _("Adresse e-mail ou rôle invalide."))
            return redirect("foyers:membres")
        try:
            invitation, jeton = services.inviter(
                foyer=self.foyer,
                invite_par=request.user,  # type: ignore[arg-type]
                **formulaire.cleaned_data,
            )
        except services.ErreurFoyer as erreur:
            messages.error(request, str(erreur))
            return redirect("foyers:membres")
        url = request.build_absolute_uri(reverse("foyers:invitation", kwargs={"jeton": jeton}))
        services.envoyer_email_invitation(invitation, url)
        messages.success(
            request, _("Invitation envoyée à %(email)s.") % {"email": invitation.email}
        )
        return redirect("foyers:membres")


class VueRevoquerInvitation(AccesFoyerMixin, View):
    portee = "foyer"
    role_ecriture = Role.ADMINISTRATEUR

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        invitation = get_object_or_404(Invitation.objects.du_foyer(self.foyer).en_attente(), pk=pk)
        services.revoquer_invitation(invitation)
        messages.success(request, _("Invitation révoquée."))
        return redirect("foyers:membres")


class VueChangerRole(AccesFoyerMixin, View):
    portee = "foyer"
    role_ecriture = Role.ADMINISTRATEUR

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        cible = get_object_or_404(Adhesion.objects.du_foyer(self.foyer), pk=pk)
        formulaire = FormulaireRole(request.POST)
        if not formulaire.is_valid():
            messages.error(request, _("Rôle inconnu."))
            return redirect("foyers:membres")
        try:
            services.changer_role(
                adhesion=cible, role=formulaire.cleaned_data["role"], par=self.adhesion
            )
        except services.ErreurFoyer as erreur:
            messages.error(request, str(erreur))
        else:
            messages.success(request, _("Rôle mis à jour."))
        return redirect("foyers:membres")


class VueRetirerMembre(AccesFoyerMixin, View):
    portee = "foyer"
    # Tout membre peut se retirer lui-même ; le service vérifie les autres cas.
    role_ecriture = Role.LECTEUR

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        cible = get_object_or_404(Adhesion.objects.du_foyer(self.foyer), pk=pk)
        se_retire = cible.pk == self.adhesion.pk
        try:
            services.retirer_membre(adhesion=cible, par=self.adhesion)
        except services.ErreurFoyer as erreur:
            messages.error(request, str(erreur))
            return redirect("foyers:membres")
        if se_retire:
            messages.success(request, _("Vous avez quitté le foyer."))
            return redirect("foyers:liste")
        messages.success(request, _("Membre retiré du foyer."))
        return redirect("foyers:membres")


class VueInvitation(LoginRequiredMixin, View):
    """Lien reçu par e-mail : seul chemin pour rejoindre un foyer.

    Le jeton prouve l'accès à la boîte aux lettres invitée ; l'adresse du compte doit en plus
    être celle de l'invitation, pour qu'un lien transféré ne serve à personne d'autre.
    """

    def _invitation(self, jeton: str) -> Invitation:
        return get_object_or_404(
            Invitation.objects.select_related("foyer"),
            empreinte_jeton=services.empreinte(jeton),
        )

    def get(self, request: HttpRequest, jeton: str) -> HttpResponse:
        invitation = self._invitation(jeton)
        contexte = {
            "invitation": invitation,
            "bonne_adresse": invitation.email == request.user.email,  # type: ignore[union-attr]
        }
        return render(request, "foyers/invitation.html", contexte)

    def post(self, request: HttpRequest, jeton: str) -> HttpResponse:
        return _accepter(request, self._invitation(jeton))


def _accepter(request: HttpRequest, invitation: Invitation) -> HttpResponse:
    try:
        adhesion = services.accepter_invitation(
            invitation=invitation,
            utilisateur=request.user,  # type: ignore[arg-type]
        )
    except services.ErreurFoyer as erreur:
        messages.error(request, str(erreur))
        return redirect("foyers:liste")
    request.session[CLE_SESSION_FOYER] = adhesion.foyer_id
    messages.success(
        request, _("Vous avez rejoint le foyer « %(nom)s ».") % {"nom": adhesion.foyer.nom}
    )
    return redirect("accueil")
