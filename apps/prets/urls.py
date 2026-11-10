from django.urls import path

from . import views

app_name = "prets"

urlpatterns = [
    path("credits/", views.VuePrets.as_view(), name="liste"),
    path("credits/ajouter/", views.VueAjouterPret.as_view(), name="ajouter"),
    path("credits/<int:pk>/", views.VuePret.as_view(), name="pret"),
    path("credits/<int:pk>/modifier/", views.VueModifierPret.as_view(), name="modifier"),
    path("credits/<int:pk>/supprimer/", views.VueSupprimerPret.as_view(), name="supprimer"),
    path(
        "credits/<int:pk>/remboursements/",
        views.VueAjouterAnticipe.as_view(),
        name="ajouter_anticipe",
    ),
    path(
        "credits/remboursements/<int:pk>/supprimer/",
        views.VueSupprimerAnticipe.as_view(),
        name="supprimer_anticipe",
    ),
]
