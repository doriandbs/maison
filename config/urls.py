from typing import Any

from django.conf import settings
from django.contrib import admin
from django.contrib.auth.views import redirect_to_login
from django.http import HttpRequest, HttpResponse
from django.urls import include, path

from apps.socle.views import sante
from apps.tableau_de_bord.views import VueEnsemble, VueTableauDeBord
from apps.utilisateurs.double_auth import est_verifie


def _connexion_admin(request: HttpRequest, extra_context: Any = None) -> HttpResponse:
    """La page de connexion propre à l'admin ne vérifie ni le code ni le nombre d'essais :
    on passe par celle de l'application."""
    return redirect_to_login(request.get_full_path())


def _acces_admin(request: HttpRequest) -> bool:
    utilisateur = request.user
    return bool(utilisateur.is_active and utilisateur.is_staff and est_verifie(utilisateur))


admin.site.login = _connexion_admin  # type: ignore[method-assign]
admin.site.has_permission = _acces_admin  # type: ignore[method-assign]

urlpatterns = [
    path("", VueTableauDeBord.as_view(), name="accueil"),
    path("sante/", sante, name="sante"),
    path("ensemble/", VueEnsemble.as_view(), name="ensemble"),
    path("compte/", include("apps.utilisateurs.urls")),
    path("", include("apps.foyers.urls")),
    path("", include("apps.banque.urls")),
    path("", include("apps.budget.urls")),
    path("", include("apps.documents.urls")),
    path("", include("apps.prets.urls")),
    path(settings.ADMIN_CHEMIN, admin.site.urls),
]
