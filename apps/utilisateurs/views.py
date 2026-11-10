from typing import Any

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import views as vues_auth
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import FormView, TemplateView

from apps.socle.limites import limiter_par_ip

from . import services
from .forms import FormulaireConnexion, FormulaireInscription


@limiter_par_ip("10/h")
class VueInscription(FormView):
    template_name = "utilisateurs/inscription.html"
    form_class = FormulaireInscription
    success_url = reverse_lazy("utilisateurs:inscription_envoyee")

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> Any:
        if not settings.INSCRIPTION_OUVERTE:
            raise Http404
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form: FormulaireInscription) -> HttpResponse:
        # Le compte reste inactif tant que l'adresse e-mail n'est pas confirmée.
        utilisateur = form.save(commit=False)
        utilisateur.is_active = False
        utilisateur.save()
        uid, jeton = services.identifiants_activation(utilisateur)
        url = self.request.build_absolute_uri(
            reverse("utilisateurs:activation", kwargs={"uidb64": uid, "jeton": jeton})
        )
        services.envoyer_email_activation(utilisateur, url)
        return super().form_valid(form)


class VueInscriptionEnvoyee(TemplateView):
    template_name = "utilisateurs/inscription_envoyee.html"


class VueActivation(View):
    def get(self, request: HttpRequest, uidb64: str, jeton: str) -> HttpResponse:
        if services.activer_compte(uidb64, jeton) is None:
            return render(request, "utilisateurs/activation_invalide.html", status=400)
        messages.success(request, _("Votre compte est activé, vous pouvez vous connecter."))
        return redirect("utilisateurs:connexion")


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
