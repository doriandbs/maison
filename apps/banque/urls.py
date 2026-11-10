from django.urls import path

from . import views

app_name = "banque"

urlpatterns = [
    path("comptes/", views.VueComptes.as_view(), name="comptes"),
    path("comptes/ajouter/", views.VueAjouterCompte.as_view(), name="ajouter_compte"),
    path("comptes/<int:pk>/", views.VueCompte.as_view(), name="compte"),
    path("comptes/deplacer/", views.VueTransfererComptes.as_view(), name="transferer_comptes"),
    path("comptes/<int:pk>/modifier/", views.VueModifierCompte.as_view(), name="modifier_compte"),
    path("comptes/<int:pk>/archiver/", views.VueArchiverCompte.as_view(), name="archiver_compte"),
    path("comptes/<int:pk>/releves/", views.VueAjouterReleve.as_view(), name="ajouter_releve"),
    path(
        "releves/<int:pk>/supprimer/", views.VueSupprimerReleve.as_view(), name="supprimer_releve"
    ),
    path("operations/", views.VueOperations.as_view(), name="operations"),
    path("operations/ajouter/", views.VueAjouterOperation.as_view(), name="ajouter_operation"),
    path(
        "operations/<int:pk>/modifier/",
        views.VueModifierOperation.as_view(),
        name="modifier_operation",
    ),
    path(
        "operations/<int:pk>/supprimer/",
        views.VueSupprimerOperation.as_view(),
        name="supprimer_operation",
    ),
    path("virements/ajouter/", views.VueAjouterVirement.as_view(), name="ajouter_virement"),
    path("operations/importer/", views.VueImporter.as_view(), name="importer"),
    path("operations/importer/apercu/", views.VueApercuImport.as_view(), name="apercu_import"),
    path("categories/regles/", views.VueRegles.as_view(), name="regles"),
    path(
        "categories/regles/appliquer/",
        views.VueAppliquerRegles.as_view(),
        name="appliquer_regles",
    ),
    path(
        "categories/regles/<int:pk>/supprimer/",
        views.VueSupprimerRegle.as_view(),
        name="supprimer_regle",
    ),
    path("categories/", views.VueCategories.as_view(), name="categories"),
    path("categories/ajouter/", views.VueAjouterCategorie.as_view(), name="ajouter_categorie"),
    path(
        "categories/<int:pk>/modifier/",
        views.VueModifierCategorie.as_view(),
        name="modifier_categorie",
    ),
    path(
        "categories/<int:pk>/archiver/",
        views.VueArchiverCategorie.as_view(),
        name="archiver_categorie",
    ),
]
