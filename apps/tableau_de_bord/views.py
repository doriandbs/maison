from typing import Any

from django.views.generic import TemplateView

from apps.foyers.acces import AccesFoyerMixin

from . import patrimoine
from .services import synthese


class VueTableauDeBord(AccesFoyerMixin, TemplateView):
    template_name = "tableau_de_bord/accueil.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexte = super().get_context_data(**kwargs)
        adhesion_foyer = getattr(self.request, "adhesion_foyer", None)
        resume = synthese(
            self.foyer, foyer_documents=adhesion_foyer.foyer if adhesion_foyer else None
        )
        contexte["synthese"] = resume
        periode = self.request.GET.get("periode")
        contexte["periode"] = int(periode) if periode in {"12", "24"} else 12
        contexte["periodes"] = patrimoine.PERIODES
        points = patrimoine.evolution(self.foyer, contexte["periode"], resume.aujourd_hui)
        contexte["evolution"] = points
        contexte["courbe"] = patrimoine.graphique(points)
        return contexte
