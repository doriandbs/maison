from typing import Any

from django.contrib import admin
from django.http import HttpRequest

from .models import Pret, RemboursementAnticipe


class RemboursementEnLigne(admin.TabularInline):
    model = RemboursementAnticipe
    extra = 0
    fields = ("date", "montant", "effet")


@admin.register(Pret)
class AdminPret(admin.ModelAdmin):
    list_display = ("nom", "foyer", "capital", "taux_annuel", "duree_mois", "premiere_echeance")
    list_select_related = ("foyer",)
    search_fields = ("nom", "foyer__nom")
    inlines = [RemboursementEnLigne]

    def save_formset(self, request: HttpRequest, form: Any, formset: Any, change: bool) -> None:
        # Les remboursements saisis dans l'admin prennent le foyer de leur prêt.
        for remboursement in formset.save(commit=False):
            remboursement.foyer = form.instance.foyer
            remboursement.save()
        formset.save_m2m()
        for supprime in formset.deleted_objects:
            supprime.delete()
