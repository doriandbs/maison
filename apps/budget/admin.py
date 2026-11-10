from django.contrib import admin

from .models import LigneBudget


@admin.register(LigneBudget)
class AdminLigneBudget(admin.ModelAdmin):
    list_display = ("categorie", "mois", "montant", "ponctuel", "foyer")
    list_filter = ("ponctuel",)
    list_select_related = ("categorie", "foyer")
