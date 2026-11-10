from typing import Any

from django.views.generic import TemplateView

from apps.foyers.acces import AccesFoyerMixin

from .services import synthese


class VueTableauDeBord(AccesFoyerMixin, TemplateView):
    template_name = "tableau_de_bord/accueil.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexte = super().get_context_data(**kwargs)
        contexte["synthese"] = synthese(self.foyer)
        return contexte
