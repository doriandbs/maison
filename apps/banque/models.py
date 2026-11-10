from __future__ import annotations

from typing import Self

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from apps.socle.models import ModeleDeFoyer, RequeteDeFoyer


class RequeteArchivable(RequeteDeFoyer):
    def actifs(self) -> Self:
        return self.filter(archive_le__isnull=True)

    def archives(self) -> Self:
        return self.filter(archive_le__isnull=False)


GestionnaireArchivable = models.Manager.from_queryset(RequeteArchivable)


class TypeCompte(models.TextChoices):
    COURANT = "courant", _("Compte courant")
    JOINT = "joint", _("Compte joint")
    LIVRET = "livret", _("Livret")
    ASSURANCE_VIE = "assurance_vie", _("Assurance vie")
    PEA = "pea", _("PEA")
    CTO = "cto", _("Compte-titres")
    PER = "per", _("PER")
    EPARGNE_SALARIALE = "epargne_salariale", _("Épargne salariale")
    CRYPTO = "crypto", _("Crypto")
    ESPECES = "especes", _("Espèces")
    AUTRE = "autre", _("Autre")


# Comptes dont la valeur fluctue : elle ne se déduit pas des opérations, on la relève.
TYPES_VALORISES = frozenset(
    {
        TypeCompte.ASSURANCE_VIE,
        TypeCompte.PEA,
        TypeCompte.CTO,
        TypeCompte.PER,
        TypeCompte.EPARGNE_SALARIALE,
        TypeCompte.CRYPTO,
    }
)


class Compte(ModeleDeFoyer):
    nom = models.CharField(_("nom"), max_length=100)
    type = models.CharField(
        _("type"), max_length=20, choices=TypeCompte.choices, default=TypeCompte.COURANT
    )
    etablissement = models.CharField(_("établissement"), max_length=100, blank=True)
    titulaires = models.ManyToManyField(
        "foyers.Adhesion", verbose_name=_("titulaires"), blank=True, related_name="comptes"
    )
    est_epargne = models.BooleanField(_("épargne ou placement"), default=False)
    solde_initial = models.DecimalField(
        _("solde initial"), max_digits=12, decimal_places=2, default=0
    )
    ouvert_le = models.DateField(
        _("date du solde initial"),
        help_text=_("Les opérations saisies doivent être postérieures à cette date."),
    )
    archive_le = models.DateTimeField(_("archivé le"), null=True, blank=True)

    objects = GestionnaireArchivable()  # type: ignore[misc]

    class Meta:
        verbose_name = _("compte")
        verbose_name_plural = _("comptes")
        ordering = ["nom"]
        constraints = [
            models.UniqueConstraint(fields=["foyer", "nom"], name="compte_nom_unique_par_foyer"),
        ]

    def __str__(self) -> str:
        return self.nom

    @property
    def est_valorise(self) -> bool:
        return self.type in TYPES_VALORISES

    @property
    def est_archive(self) -> bool:
        return self.archive_le is not None


class ReleveSolde(ModeleDeFoyer):
    """Valeur d'un compte constatée à une date (fin de mois pour un placement)."""

    compte = models.ForeignKey(
        Compte, verbose_name=_("compte"), on_delete=models.CASCADE, related_name="releves"
    )
    date = models.DateField(_("date"))
    montant = models.DecimalField(_("montant"), max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = _("relevé de solde")
        verbose_name_plural = _("relevés de solde")
        ordering = ["-date"]
        constraints = [
            models.UniqueConstraint(fields=["compte", "date"], name="releve_unique_par_jour"),
        ]

    def __str__(self) -> str:
        return f"{self.compte} – {self.date:%d/%m/%Y}"


class Nature(models.TextChoices):
    DEPENSE = "depense", _("Dépense")
    REVENU = "revenu", _("Revenu")


class Categorie(ModeleDeFoyer):
    """Catégorie sur deux niveaux : une catégorie parente et ses sous-catégories.

    Les opérations se rangent uniquement dans des sous-catégories.
    """

    nom = models.CharField(_("nom"), max_length=100)
    nature = models.CharField(
        _("nature"), max_length=10, choices=Nature.choices, default=Nature.DEPENSE
    )
    parent = models.ForeignKey(
        "self",
        verbose_name=_("catégorie parente"),
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sous_categories",
    )
    archive_le = models.DateTimeField(_("archivée le"), null=True, blank=True)

    objects = GestionnaireArchivable()  # type: ignore[misc]

    class Meta:
        verbose_name = _("catégorie")
        verbose_name_plural = _("catégories")
        ordering = ["nom"]
        constraints = [
            models.UniqueConstraint(
                fields=["foyer", "nom"],
                condition=Q(parent__isnull=True),
                name="categorie_parente_nom_unique",
            ),
            models.UniqueConstraint(
                fields=["parent", "nom"],
                condition=Q(parent__isnull=False),
                name="sous_categorie_nom_unique",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.parent.nom} › {self.nom}" if self.parent is not None else self.nom

    @property
    def est_archivee(self) -> bool:
        return self.archive_le is not None

    def clean(self) -> None:
        if self.parent is None:
            return
        if self.parent.foyer_id != self.foyer_id:
            raise ValidationError(_("La catégorie parente appartient à un autre foyer."))
        if self.parent.parent_id is not None:
            raise ValidationError(_("Une sous-catégorie ne peut pas avoir de sous-catégories."))
        if self.pk and self.sous_categories.exists():
            raise ValidationError(
                _("Cette catégorie a des sous-catégories : elle ne peut pas en devenir une.")
            )
        self.nature = self.parent.nature


class Operation(ModeleDeFoyer):
    compte = models.ForeignKey(
        Compte, verbose_name=_("compte"), on_delete=models.PROTECT, related_name="operations"
    )
    date = models.DateField(_("date"))
    libelle = models.CharField(_("libellé"), max_length=200)
    montant = models.DecimalField(
        _("montant"),
        max_digits=12,
        decimal_places=2,
        help_text=_("Négatif pour une sortie d'argent, positif pour une entrée."),
    )
    categorie = models.ForeignKey(
        Categorie,
        verbose_name=_("catégorie"),
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="operations",
    )
    note = models.TextField(_("note"), blank=True)
    # Texte complet fourni par la banque lors d'un import (le libellé, lui, est raccourci).
    libelle_banque = models.TextField(_("libellé de la banque"), blank=True, editable=False)
    # Empreinte de la ligne du relevé : réimporter une période déjà vue ne crée pas de doublon.
    # NULL plutôt que chaîne vide : l'unicité ne porte que sur les lignes importées.
    empreinte_import = models.CharField(  # noqa: DJ001
        max_length=64, null=True, blank=True, editable=False
    )
    # Les deux opérations d'un virement interne partagent ce groupe ; elles ne
    # comptent ni en revenu ni en dépense.
    groupe_virement = models.UUIDField(null=True, blank=True, editable=False, db_index=True)
    cree_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("créée par"),
        null=True,
        editable=False,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        verbose_name = _("opération")
        verbose_name_plural = _("opérations")
        ordering = ["-date", "-id"]
        indexes = [
            models.Index(fields=["foyer", "date"], name="operation_foyer_date"),
            models.Index(fields=["compte", "date"], name="operation_compte_date"),
        ]
        constraints = [
            models.CheckConstraint(condition=~Q(montant=0), name="operation_montant_non_nul"),
            models.CheckConstraint(
                condition=Q(groupe_virement__isnull=True) | Q(categorie__isnull=True),
                name="operation_virement_sans_categorie",
            ),
            models.UniqueConstraint(
                fields=["compte", "empreinte_import"],
                condition=Q(empreinte_import__isnull=False),
                name="operation_import_unique",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.date:%d/%m/%Y} {self.libelle} ({self.montant})"

    @property
    def est_virement(self) -> bool:
        return self.groupe_virement is not None

    def clean(self) -> None:
        if self.compte_id and self.compte.foyer_id != self.foyer_id:
            raise ValidationError(_("Le compte appartient à un autre foyer."))
        if self.categorie_id and self.categorie.foyer_id != self.foyer_id:  # type: ignore[union-attr]
            raise ValidationError(_("La catégorie appartient à un autre foyer."))


class RegleCategorisation(ModeleDeFoyer):
    """« Libellé contient <motif> » → sous-catégorie. Le motif le plus long l'emporte."""

    motif = models.CharField(
        _("le libellé contient"),
        max_length=100,
        help_text=_("Sans tenir compte des majuscules ni des accents. Ex. : « SNCF », « Free »."),
    )
    categorie = models.ForeignKey(
        Categorie,
        verbose_name=_("catégorie"),
        on_delete=models.CASCADE,
        related_name="regles",
    )

    class Meta:
        verbose_name = _("règle de catégorisation")
        verbose_name_plural = _("règles de catégorisation")
        ordering = ["motif"]
        constraints = [
            models.UniqueConstraint(
                Lower("motif"), F("foyer"), name="regle_motif_unique_par_foyer"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.motif} → {self.categorie}"

    def clean(self) -> None:
        self.motif = " ".join(self.motif.split())
        if self.categorie_id and self.categorie.foyer_id != self.foyer_id:
            raise ValidationError(_("La catégorie appartient à un autre foyer."))
        if self.categorie_id and self.categorie.parent_id is None:
            raise ValidationError(_("Choisissez une sous-catégorie."))
