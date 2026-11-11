from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.socle.models import ModeleDeFoyer

from .services.amortissement import (
    Anticipe,
    Conditions,
    Differe,
    Effet,
    Tableau,
    ajouter_mois,
    calculer,
)


class TypeDiffere(models.TextChoices):
    AUCUN = Differe.AUCUN, _("Aucun")
    PARTIEL = Differe.PARTIEL, _("Partiel (intérêts et assurance payés)")
    TOTAL = Differe.TOTAL, _("Total (assurance seule, intérêts reportés)")


class EffetAnticipe(models.TextChoices):
    DUREE = Effet.DUREE, _("Réduire la durée")
    MENSUALITE = Effet.MENSUALITE, _("Réduire la mensualité")


class Pret(ModeleDeFoyer):
    nom = models.CharField(_("nom"), max_length=100, help_text=_("Ex. « Crédit immobilier »."))
    etablissement = models.CharField(_("établissement"), max_length=100, blank=True)
    capital = models.DecimalField(
        _("montant emprunté"),
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("1"))],
    )
    taux_annuel = models.DecimalField(
        _("taux nominal annuel (%)"),
        max_digits=6,
        decimal_places=3,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("30"))],
        help_text=_("Le taux du prêt, hors assurance (pas le TAEG). Ex. 3,45."),
    )
    duree_mois = models.PositiveSmallIntegerField(
        _("durée totale (mois)"),
        validators=[MinValueValidator(1), MaxValueValidator(600)],
        help_text=_("Différé compris. 25 ans = 300 mois."),
    )
    premiere_echeance = models.DateField(
        _("date de la première échéance"),
        help_text=_("Le premier prélèvement, même s'il ne contient que l'assurance (différé)."),
    )
    signe_le = models.DateField(
        _("date de signature"),
        null=True,
        blank=True,
        help_text=_(
            "Ou du premier déblocage des fonds. Le crédit et le bien comptent dans votre "
            "patrimoine à partir de cette date. Vide : un mois avant la première échéance."
        ),
    )
    assurance_mensuelle = models.DecimalField(
        _("assurance par mois"), max_digits=10, decimal_places=2, default=0
    )
    differe_mois = models.PositiveSmallIntegerField(_("durée du différé (mois)"), default=0)
    type_differe = models.CharField(
        _("type de différé"), max_length=10, choices=TypeDiffere.choices, default=TypeDiffere.AUCUN
    )
    compte = models.ForeignKey(
        "banque.Compte",
        verbose_name=_("compte débité"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="prets",
    )
    valeur_bien = models.DecimalField(
        _("valeur estimée du bien"),
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_(
            "Facultatif. Comptée dans le patrimoine net, face au capital restant dû : sans elle, "
            "un crédit immobilier ferait paraître le patrimoine négatif."
        ),
    )

    class Meta:
        verbose_name = _("prêt")
        verbose_name_plural = _("prêts")
        ordering = ["premiere_echeance", "nom"]

    def __str__(self) -> str:
        return self.nom

    @property
    def debut(self) -> date:
        """À partir de quand le prêt existe : dette due et bien possédé."""
        return self.signe_le or ajouter_mois(self.premiere_echeance, -1)

    def clean(self) -> None:
        if self.compte_id and self.compte.foyer_id != self.foyer_id:  # type: ignore[union-attr]
            raise ValidationError(_("Le compte appartient à un autre foyer."))
        if self.type_differe == TypeDiffere.AUCUN:
            self.differe_mois = 0
        elif not self.differe_mois:
            raise ValidationError({"differe_mois": _("Indiquez la durée du différé.")})
        if self.signe_le and self.premiere_echeance and self.signe_le > self.premiere_echeance:
            raise ValidationError(
                {"signe_le": _("La signature précède forcément la première échéance.")}
            )
        if self.duree_mois and self.differe_mois >= self.duree_mois:
            raise ValidationError(
                {"differe_mois": _("Le différé doit être plus court que le prêt.")}
            )

    @property
    def conditions(self) -> Conditions:
        return Conditions(
            capital=self.capital,
            taux_annuel=self.taux_annuel,
            duree_mois=self.duree_mois,
            premiere_echeance=self.premiere_echeance,
            assurance_mensuelle=self.assurance_mensuelle,
            differe_mois=self.differe_mois,
            type_differe=self.type_differe,
        )

    def anticipes(self) -> list[Anticipe]:
        return [
            Anticipe(remboursement.date, remboursement.montant, remboursement.effet)
            for remboursement in self.remboursements.all()
        ]

    def tableau(self) -> Tableau:
        return calculer(self.conditions, self.anticipes())


class RemboursementAnticipe(ModeleDeFoyer):
    pret = models.ForeignKey(
        Pret, verbose_name=_("prêt"), on_delete=models.CASCADE, related_name="remboursements"
    )
    date = models.DateField(_("date"))
    montant = models.DecimalField(
        _("montant"),
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    effet = models.CharField(
        _("effet"), max_length=10, choices=EffetAnticipe.choices, default=EffetAnticipe.DUREE
    )

    class Meta:
        verbose_name = _("remboursement anticipé")
        verbose_name_plural = _("remboursements anticipés")
        ordering = ["date"]

    def __str__(self) -> str:
        return f"{self.pret} – {self.date:%d/%m/%Y}"
