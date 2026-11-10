from django.contrib import admin

from .models import Adhesion, Foyer, Invitation


class AdhesionEnLigne(admin.TabularInline):
    model = Adhesion
    extra = 0
    autocomplete_fields = ("utilisateur",)


@admin.register(Foyer)
class AdminFoyer(admin.ModelAdmin):
    list_display = ("nom", "cree_par", "cree_le")
    search_fields = ("nom",)
    inlines = [AdhesionEnLigne]


@admin.register(Invitation)
class AdminInvitation(admin.ModelAdmin):
    list_display = ("email", "foyer", "role", "expire_le", "acceptee_le", "revoquee_le")
    list_filter = ("role",)
    search_fields = ("email", "foyer__nom")
