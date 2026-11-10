from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

app_name = "utilisateurs"

urlpatterns = [
    path("inscription/", views.VueInscription.as_view(), name="inscription"),
    path("inscription/envoyee/", views.VueInscriptionEnvoyee.as_view(), name="inscription_envoyee"),
    path("activer/<uidb64>/<jeton>/", views.VueActivation.as_view(), name="activation"),
    path("connexion/", views.VueConnexion.as_view(), name="connexion"),
    path("deconnexion/", LogoutView.as_view(), name="deconnexion"),
    path("mot-de-passe/oublie/", views.VueMotDePasseOublie.as_view(), name="mot_de_passe_oublie"),
    path("mot-de-passe/envoye/", views.VueMotDePasseEnvoye.as_view(), name="mot_de_passe_envoye"),
    path(
        "mot-de-passe/nouveau/<uidb64>/<token>/",
        views.VueMotDePasseNouveau.as_view(),
        name="mot_de_passe_nouveau",
    ),
    path(
        "mot-de-passe/termine/",
        views.VueMotDePasseTermine.as_view(),
        name="mot_de_passe_termine",
    ),
]
