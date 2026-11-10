from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

app_name = "utilisateurs"

urlpatterns = [
    path("inscription/", views.VueInscription.as_view(), name="inscription"),
    path("connexion/", views.VueConnexion.as_view(), name="connexion"),
    path("deconnexion/", LogoutView.as_view(), name="deconnexion"),
    path("verification/", views.VueVerification.as_view(), name="verification"),
    path(
        "double-authentification/activer/",
        views.VueActiverDoubleAuth.as_view(),
        name="activer_double_auth",
    ),
    path("codes-de-secours/", views.VueCodesSecours.as_view(), name="codes_secours"),
    path("", views.VueMonCompte.as_view(), name="compte"),
    path("mot-de-passe/", views.VueChangerMotDePasse.as_view(), name="changer_mot_de_passe"),
    path("appareils/oublier/", views.VueOublierAppareils.as_view(), name="oublier_appareils"),
    path("telephone/changer/", views.VueChangerTelephone.as_view(), name="changer_telephone"),
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
