from django.urls import path

from . import views

app_name = "foyers"

urlpatterns = [
    # Tous les foyers de l'utilisateur
    path("foyers/", views.VueMesFoyers.as_view(), name="liste"),
    path("foyers/creer/", views.VueCreerFoyer.as_view(), name="creer"),
    path("foyers/<int:pk>/activer/", views.VueActiverFoyer.as_view(), name="activer"),
    path("foyers/<int:pk>/principal/", views.VueFoyerPrincipal.as_view(), name="principal"),
    # Foyer courant
    path("foyer/membres/", views.VueMembres.as_view(), name="membres"),
    path("foyer/membres/<int:pk>/role/", views.VueChangerRole.as_view(), name="changer_role"),
    path(
        "foyer/membres/<int:pk>/retirer/", views.VueRetirerMembre.as_view(), name="retirer_membre"
    ),
    path("foyer/invitations/", views.VueInviter.as_view(), name="inviter"),
    path(
        "foyer/invitations/<int:pk>/revoquer/",
        views.VueRevoquerInvitation.as_view(),
        name="revoquer_invitation",
    ),
    # Lien reçu par e-mail : seul moyen de rejoindre un foyer.
    path("invitations/<str:jeton>/", views.VueInvitation.as_view(), name="invitation"),
]
