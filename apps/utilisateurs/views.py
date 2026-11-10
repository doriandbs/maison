from typing import Any

from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth import views as vues_auth
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.generic import FormView

from apps.socle.limites import limiter_par_ip

from .forms import FormulaireConnexion, FormulaireInscription


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
        return redirect(self._page_suivante() or settings.LOGIN_REDIRECT_URL)

    def _page_suivante(self) -> str | None:
        """Page demandée avant l'inscription (lien d'invitation), si elle est sur ce site."""
        suivante = self.request.POST.get("next") or self.request.GET.get("next", "")
        sure = url_has_allowed_host_and_scheme(
            suivante,
            allowed_hosts={self.request.get_host()},
            require_https=self.request.is_secure(),
        )
        return suivante if sure else None

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexte = super().get_context_data(**kwargs)
        contexte["next"] = self._page_suivante() or ""
        return contexte


@limiter_par_ip("30/h")
class VueConnexion(vues_auth.LoginView):
    template_name = "utilisateurs/connexion.html"
    authentication_form = FormulaireConnexion
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexte = super().get_context_data(**kwargs)
        contexte["inscription_ouverte"] = settings.INSCRIPTION_OUVERTE
        return contexte


@limiter_par_ip("5/h")
class VueMotDePasseOublie(vues_auth.PasswordResetView):
    template_name = "utilisateurs/mot_de_passe_oublie.html"
    email_template_name = "utilisateurs/emails/reinitialisation.txt"
    subject_template_name = "utilisateurs/emails/reinitialisation_sujet.txt"
    success_url = reverse_lazy("utilisateurs:mot_de_passe_envoye")


class VueMotDePasseEnvoye(vues_auth.PasswordResetDoneView):
    template_name = "utilisateurs/mot_de_passe_envoye.html"


class VueMotDePasseNouveau(vues_auth.PasswordResetConfirmView):
    template_name = "utilisateurs/mot_de_passe_nouveau.html"
    success_url = reverse_lazy("utilisateurs:mot_de_passe_termine")


class VueMotDePasseTermine(vues_auth.PasswordResetCompleteView):
    template_name = "utilisateurs/mot_de_passe_termine.html"
