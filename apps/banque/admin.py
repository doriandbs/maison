from django.contrib import admin

from .models import Categorie, Compte, Operation, ReleveSolde


@admin.register(Compte)
class AdminCompte(admin.ModelAdmin):
    list_display = ("nom", "foyer", "type", "etablissement", "archive_le")
    list_filter = ("type",)
    search_fields = ("nom", "foyer__nom")


@admin.register(Categorie)
class AdminCategorie(admin.ModelAdmin):
    list_display = ("nom", "parent", "foyer", "nature", "archive_le")
    list_filter = ("nature",)
    search_fields = ("nom", "foyer__nom")


@admin.register(Operation)
class AdminOperation(admin.ModelAdmin):
    list_display = ("date", "libelle", "montant", "compte", "categorie", "foyer")
    date_hierarchy = "date"
    search_fields = ("libelle",)
    list_select_related = ("compte", "categorie", "foyer")


@admin.register(ReleveSolde)
class AdminReleveSolde(admin.ModelAdmin):
    list_display = ("compte", "date", "montant", "foyer")
    list_select_related = ("compte", "foyer")
