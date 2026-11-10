from typing import Any
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import views as vues_auth
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views import View
from django.views.decorators.cache import never_cache
from django.views.generic import FormView, TemplateView

from apps.socle.limites import limiter_par_ip, limiter_par_utilisateur
from apps.socle.views import PageFormulaireMixin

from . import double_auth
from .forms import (
    FormulaireActivation,
    FormulaireCode,
    FormulaireConfirmationMotDePasse,
    FormulaireConnexion,
    FormulaireInscription,
)
from .models import Utilisateur

CLE_CODES_A_AFFICHER = "codes_secours_a_afficher"


def page_suivante(request: HttpRequest) -> str | None:
    """Page demandée avant la connexion (lien d'invitation…), si elle est sur ce site."""
    suivante = request.POST.get("next") or request.GET.get("next", "")
    sure = url_has_allowed_host_and_scheme(
        suivante, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    )
    return suivante if sure else None


def _avec_suivante(route: str, request: HttpRequest) -> str:
    suivante = page_suivante(request)
    return f"{reverse(route)}?{urlencode({'next': suivante})}" if suivante else reverse(route)


def _utilisateur(request: HttpRequest) -> Utilisateur:
    return request.user  # type: ignore[return-value]


# --- Inscription et connexion ------------------------------------------------


@limiter_par_ip("10/h")
class VueInscription(FormView):
    template_name = "utilisateurs/inscription.html"
    form_class = FormulaireInscription

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> Any:
        if not settings.INSCRIPTION_OUVERTE:
            raise Http404
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form: FormulaireInscription) -> HttpResponse:
        utilisateur = form.save()
        login(self.request, utilisateur, backend="django.contrib.auth.backends.ModelBackend")
        return redirect(page_suivante(self.request) or settings.LOGIN_REDIRECT_URL)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexte = super().get_context_data(**kwargs)
        contexte["next"] = page_suivante(self.request) or ""
        return contexte


@limiter_par_ip("30/h")
class VueConnexion(vues_auth.LoginView):
    """Première étape : le mot de passe. La seconde (code) est imposée par
    `IntergicielDoubleAuthentification`."""

    template_name = "utilisateurs/connexion.html"
    authentication_form = FormulaireConnexion
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexte = super().get_context_data(**kwargs)
        contexte["inscription_ouverte"] = settings.INSCRIPTION_OUVERTE
        return contexte


# --- Double authentification ------------------------------------------------


@method_decorator(never_cache, name="dispatch")
@limiter_par_utilisateur("30/h")
class VueVerification(LoginRequiredMixin, FormView):
    """Seconde étape de la connexion : code de l'application ou code de secours."""

    template_name = "utilisateurs/verification.html"
    form_class = FormulaireCode

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> Any:
        if request.user.is_authenticated:
            if request.acces_complet:  # type: ignore[attr-defined]
                return redirect(page_suivante(request) or settings.LOGIN_REDIRECT_URL)
            if not double_auth.est_configuree(_utilisateur(request)):
                return redirect(_avec_suivante("utilisateurs:activer_double_auth", request))
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form: FormulaireCode) -> HttpResponse:
        utilisateur = _utilisateur(self.request)
        appareil = double_auth.verifier_code(utilisateur, form.cleaned_data["code"])
        if appareil is None:
            erreur = (
                _("Trop d'essais : patientez quelques secondes avant de réessayer.")
                if double_auth.essais_bloques(utilisateur)
                else _("Code incorrect ou expiré.")
            )
            form.add_error("code", erreur)
            return self.form_invalid(form)
        double_auth.valider_session(self.request, appareil)
        if appareil.persistent_id.startswith("otp_static"):
            messages.warning(
                self.request,
                _("Code de secours utilisé. Il vous en reste %(n)d.")
                % {"n": double_auth.codes_secours_restants(utilisateur)},
            )
        reponse = redirect(page_suivante(self.request) or settings.LOGIN_REDIRECT_URL)
        if form.cleaned_data["memoriser"]:
            double_auth.memoriser_appareil(self.request, reponse)
        return reponse

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexte = super().get_context_data(**kwargs)
        contexte["next"] = page_suivante(self.request) or ""
        return contexte


@method_decorator(never_cache, name="dispatch")
@limiter_par_utilisateur("30/h")
class VueActiverDoubleAuth(LoginRequiredMixin, FormView):
    """Configuration de l'application : obligatoire avant tout accès aux données."""

    template_name = "utilisateurs/activer_double_auth.html"
    form_class = FormulaireActivation

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> Any:
        if request.user.is_authenticated and double_auth.est_configuree(_utilisateur(request)):
            if request.acces_complet:  # type: ignore[attr-defined]
                return redirect("utilisateurs:compte")
            return redirect(_avec_suivante("utilisateurs:verification", request))
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexte = super().get_context_data(**kwargs)
        appareil = double_auth.preparer_application(_utilisateur(self.request))
        contexte["qr_code"] = double_auth.qr_code_svg(appareil)
        contexte["cle"] = double_auth.cle_lisible(appareil)
        contexte["next"] = page_suivante(self.request) or ""
        return contexte

    def form_valid(self, form: FormulaireActivation) -> HttpResponse:
        appareil = double_auth.preparer_application(_utilisateur(self.request))
        codes = double_auth.confirmer_application(appareil, form.cleaned_data["code"])
        if codes is None:
            form.add_error("code", _("Code incorrect. Vérifiez l'heure de votre téléphone."))
            return self.form_invalid(form)
        double_auth.valider_session(self.request, appareil)
        self.request.session[CLE_CODES_A_AFFICHER] = codes
        return redirect(_avec_suivante("utilisateurs:codes_secours", self.request))


@method_decorator(never_cache, name="dispatch")
class VueCodesSecours(LoginRequiredMixin, View):
    """Affiche les codes de secours une seule fois, juste après leur création."""

    def get(self, request: HttpRequest) -> HttpResponse:
        codes = request.session.pop(CLE_CODES_A_AFFICHER, None)
        if not codes:
            return redirect("utilisateurs:compte")
        suivante = page_suivante(request) or reverse("utilisateurs:compte")
        return render(
            request, "utilisateurs/codes_secours.html", {"codes": codes, "suivante": suivante}
        )

    def post(self, request: HttpRequest) -> HttpResponse:
        request.session[CLE_CODES_A_AFFICHER] = double_auth.generer_codes_secours(
            _utilisateur(request)
        )
        return redirect("utilisateurs:codes_secours")


# --- Mon compte ---------------------------------------------------------------


class VueMonCompte(LoginRequiredMixin, TemplateView):
    template_name = "utilisateurs/compte.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexte = super().get_context_data(**kwargs)
        utilisateur = _utilisateur(self.request)
        contexte["double_auth_active"] = double_auth.est_configuree(utilisateur)
        contexte["codes_restants"] = double_auth.codes_secours_restants(utilisateur)
        contexte["formulaire_telephone"] = FormulaireConfirmationMotDePasse(utilisateur=utilisateur)
        return contexte


class VueChangerMotDePasse(PageFormulaireMixin, vues_auth.PasswordChangeView):
    titre = gettext_lazy("Changer de mot de passe")
    url_retour = reverse_lazy("utilisateurs:compte")

    def form_valid(self, form: PasswordChangeForm) -> HttpResponse:
        reponse = super().form_valid(form)
        double_auth.oublier_appareils(_utilisateur(self.request))
        messages.success(
            self.request,
            _("Mot de passe modifié. Vos autres sessions et appareils mémorisés sont fermés."),
        )
        return reponse


class VueOublierAppareils(LoginRequiredMixin, View):
    def post(self, request: HttpRequest) -> HttpResponse:
        double_auth.oublier_appareils(_utilisateur(request))
        messages.success(request, _("Le code sera de nouveau demandé sur tous vos appareils."))
        return redirect("utilisateurs:compte")


@limiter_par_utilisateur("10/h")
class VueChangerTelephone(LoginRequiredMixin, View):
    """Retire l'application actuelle (mot de passe exigé) puis lance la nouvelle activation."""

    def post(self, request: HttpRequest) -> HttpResponse:
        formulaire = FormulaireConfirmationMotDePasse(
            request.POST, utilisateur=_utilisateur(request)
        )
        if not formulaire.is_valid():
            messages.error(request, _("Mot de passe incorrect : rien n'a été modifié."))
            return redirect("utilisateurs:compte")
        double_auth.retirer(_utilisateur(request))
        return redirect("utilisateurs:activer_double_auth")


# --- Mot de passe oublié ------------------------------------------------------


@limiter_par_ip("5/h")
class VueMotDePasseOublie(vues_auth.PasswordResetView):
    template_name = "utilisateurs/mot_de_passe_oublie.html"
    email_template_name = "utilisateurs/emails/reinitialisation.txt"
    subject_template_name = "utilisateurs/emails/reinitialisation_sujet.txt"
    success_url = reverse_lazy("utilisateurs:mot_de_passe_envoye")


class VueMotDePasseEnvoye(vues_auth.PasswordResetDoneView):
    template_name = "utilisateurs/mot_de_passe_envoye.html"


class VueMotDePasseNouveau(vues_auth.PasswordResetConfirmView):
    """La réinitialisation ne connecte pas : le code reste exigé à la connexion suivante."""

    template_name = "utilisateurs/mot_de_passe_nouveau.html"
    success_url = reverse_lazy("utilisateurs:mot_de_passe_termine")

    def form_valid(self, form: SetPasswordForm) -> HttpResponse:
        reponse = super().form_valid(form)
        double_auth.oublier_appareils(form.user)
        return reponse


class VueMotDePasseTermine(vues_auth.PasswordResetCompleteView):
    template_name = "utilisateurs/mot_de_passe_termine.html"
