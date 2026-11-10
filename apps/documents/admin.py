from django.contrib import admin

from .models import Document


@admin.register(Document)
class AdminDocument(admin.ModelAdmin):
    list_display = ("titre", "type", "emetteur", "date", "montant", "paye_le", "foyer")
    list_filter = ("type",)
    date_hierarchy = "date"
    search_fields = ("titre", "emetteur")
    list_select_related = ("foyer",)
    # Le fichier ne se remplace que par l'application, qui contrôle son type réel.
    readonly_fields = ("fichier", "nom_fichier", "type_mime", "taille")
