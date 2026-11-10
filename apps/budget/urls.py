from django.urls import path

from . import views

app_name = "budget"

urlpatterns = [
    path("budget/", views.VueBudgetCourant.as_view(), name="courant"),
    path("budget/<int:annee>/", views.VueRecapAnnuel.as_view(), name="annee"),
    path("budget/<int:annee>/<int:mois>/", views.VueTableauMensuel.as_view(), name="mois"),
    path(
        "budget/<int:annee>/<int:mois>/previsionnel/",
        views.VuePrevisionnel.as_view(),
        name="previsionnel",
    ),
]
