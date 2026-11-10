from django.contrib import admin
from django.urls import include, path

from apps.foyers.views import VueAccueil
from apps.socle.views import sante

urlpatterns = [
    path("", VueAccueil.as_view(), name="accueil"),
    path("sante/", sante, name="sante"),
    path("compte/", include("apps.utilisateurs.urls")),
    path("", include("apps.foyers.urls")),
    path("", include("apps.banque.urls")),
    path("admin/", admin.site.urls),
]
