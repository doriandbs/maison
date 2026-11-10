from django.urls import path

from . import views

app_name = "documents"

urlpatterns = [
    path("documents/", views.VueDocuments.as_view(), name="liste"),
    path("documents/ajouter/", views.VueAjouterDocument.as_view(), name="ajouter"),
    path("documents/<int:pk>/", views.VueDocument.as_view(), name="document"),
    path("documents/<int:pk>/modifier/", views.VueModifierDocument.as_view(), name="modifier"),
    path("documents/<int:pk>/supprimer/", views.VueSupprimerDocument.as_view(), name="supprimer"),
    path("documents/<int:pk>/paiement/", views.VueBasculerPaiement.as_view(), name="paiement"),
    path("documents/<int:pk>/fichier/", views.VueFichierDocument.as_view(), name="fichier"),
]
