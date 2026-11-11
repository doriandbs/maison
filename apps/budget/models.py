from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.socle.models import ModeleDeFoyer


class LigneBudget(ModeleDeFoyer):
    """Budget prévu pour une catégorie (parente ou sous-catégorie).

    Une ligne ordinaire vaut à partir de son mois et pour les suivants, jusqu'à la
    prochaine ligne. Une ligne ponctuelle ne vaut que pour son mois et prime sur les
    autres. Un montant nul signifie « plus de budget ».
    Seul le tableau mensuel est calculé : voir `budget.services.previsionnel`.
    """

    # Commun à tout le foyer (voir socle.perimetre), pas à l'espace d'une personne.
    porte_le_classement = True

    categorie = models.ForeignKey(
        "banque.Categorie",
        verbose_name=_("catégorie"),
        on_delete=models.CASCADE,
        related_name="lignes_budget",
    )
    mois = models.DateField(_("mois"), help_text=_("Premier jour du mois concerné."))
    montant = models.DecimalField(_("montant"), max_digits=12, decimal_places=2)
    ponctuel = models.BooleanField(_("ce mois uniquement"), default=False)

    class Meta:
        verbose_name = _("ligne de budget")
        verbose_name_plural = _("lignes de budget")
        ordering = ["mois"]
        constraints = [
            models.UniqueConstraint(
                fields=["categorie", "mois", "ponctuel"], name="ligne_budget_unique"
            ),
            models.CheckConstraint(
                condition=Q(montant__gte=0), name="ligne_budget_montant_positif"
            ),
            models.CheckConstraint(condition=Q(mois__day=1), name="ligne_budget_premier_du_mois"),
        ]

    def __str__(self) -> str:
        return f"{self.categorie} – {self.mois:%m/%Y} : {self.montant}"
