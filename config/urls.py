from django.contrib import admin
from django.urls import include, path

from apps.socle.views import sante
from apps.tableau_de_bord.views import VueTableauDeBord

urlpatterns = [
    path("", VueTableauDeBord.as_view(), name="accueil"),
    path("sante/", sante, name="sante"),
    path("compte/", include("apps.utilisateurs.urls")),
    path("", include("apps.foyers.urls")),
    path("", include("apps.banque.urls")),
    path("", include("apps.budget.urls")),
    path("", include("apps.documents.urls")),
    path("admin/", admin.site.urls),
]
