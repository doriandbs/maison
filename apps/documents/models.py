from __future__ import annotations

import uuid
from typing import Self

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.socle.models import ModeleDeFoyer, RequeteDeFoyer


class TypeDocument(models.TextChoices):
    FACTURE = "facture", _("Facture")
    CONTRAT = "contrat", _("Contrat")
    GARANTIE = "garantie", _("Garantie")
    AUTRE = "autre", _("Autre")


# Types acceptés, reconnus à leur contenu et non à leur extension.
EXTENSIONS_PAR_TYPE = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}


def chemin_document(document: Document, nom_original: str) -> str:
    """`documents/<foyer>/<uuid>.<ext>` : le nom choisi par l'utilisateur n'atteint jamais
    le disque, et l'extension découle du type réellement détecté."""
    extension = EXTENSIONS_PAR_TYPE[document.type_mime]
    return f"documents/{document.foyer_id}/{uuid.uuid4().hex}{extension}"


class RequeteDocument(RequeteDeFoyer):
    def a_payer(self) -> Self:
        return self.filter(type=TypeDocument.FACTURE, paye_le__isnull=True)


GestionnaireDocument = models.Manager.from_queryset(RequeteDocument)


class Document(ModeleDeFoyer):
    titre = models.CharField(_("titre"), max_length=200)
    type = models.CharField(
        _("type"), max_length=20, choices=TypeDocument.choices, default=TypeDocument.FACTURE
    )
    emetteur = models.CharField(_("émetteur"), max_length=200, blank=True)
    date = models.DateField(_("date du document"))
    montant = models.DecimalField(
        _("montant"), max_digits=12, decimal_places=2, null=True, blank=True
    )
    echeance = models.DateField(_("échéance"), null=True, blank=True)
    paye_le = models.DateField(_("payée le"), null=True, blank=True)

    fichier = models.FileField(_("fichier"), upload_to=chemin_document, max_length=255)
    nom_fichier = models.CharField(_("nom du fichier"), max_length=255, editable=False)
    type_mime = models.CharField(max_length=100, editable=False)
    taille = models.PositiveIntegerField(_("taille (octets)"), editable=False)

    categorie = models.ForeignKey(
        "banque.Categorie",
        verbose_name=_("catégorie"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="documents",
    )
    compte = models.ForeignKey(
        "banque.Compte",
        verbose_name=_("compte"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="documents",
    )
    # La pièce jointe d'une opération est un document lié (ADR 0003).
    operation = models.ForeignKey(
        "banque.Operation",
        verbose_name=_("opération"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="documents",
    )
    note = models.TextField(_("note"), blank=True)
    cree_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("déposé par"),
        null=True,
        editable=False,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    objects = GestionnaireDocument()  # type: ignore[misc]

    class Meta:
        verbose_name = _("document")
        verbose_name_plural = _("documents")
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["foyer", "date"], name="document_foyer_date")]
        constraints = [
            models.CheckConstraint(
                condition=Q(paye_le__isnull=True) | Q(type=TypeDocument.FACTURE),
                name="document_seule_une_facture_se_paie",
            ),
        ]

    def __str__(self) -> str:
        return self.titre

    @property
    def est_facture(self) -> bool:
        return self.type == TypeDocument.FACTURE

    @property
    def est_a_payer(self) -> bool:
        return self.est_facture and self.paye_le is None

    @property
    def est_image(self) -> bool:
        return self.type_mime.startswith("image/")

    def clean(self) -> None:
        for lien in (self.categorie, self.compte, self.operation):
            if lien is not None and lien.foyer_id != self.foyer_id:
                raise ValidationError(_("Un élément lié appartient à un autre foyer."))
        if not self.est_facture:
            self.paye_le = None
