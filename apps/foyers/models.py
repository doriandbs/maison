from __future__ import annotations

from typing import Self

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.socle.models import ModeleDeFoyer, ModeleHorodate, RequeteDeFoyer


class Role(models.TextChoices):
    PROPRIETAIRE = "proprietaire", _("Propriétaire")
    ADMINISTRATEUR = "administrateur", _("Administrateur")
    MEMBRE = "membre", _("Membre")
    LECTEUR = "lecteur", _("Lecture seule")


NIVEAU_PAR_ROLE: dict[str, int] = {
    Role.LECTEUR: 0,
    Role.MEMBRE: 1,
    Role.ADMINISTRATEUR: 2,
    Role.PROPRIETAIRE: 3,
}


class Foyer(ModeleHorodate):
    nom = models.CharField(_("nom"), max_length=100)
    cree_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("créé par"),
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    membres = models.ManyToManyField(
        settings.AUTH_USER_MODEL, through="Adhesion", related_name="foyers"
    )
    # Renseigné : ce « foyer » est l'espace financier personnel de cette personne
    # (comptes, budget, crédits…), créé automatiquement et jamais présenté comme un foyer.
    # Vide : un vrai foyer partagé (membres, documents). Voir docs/adr/0006.
    personne = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name=_("espace personnel de"),
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="espace",
    )

    class Meta:
        verbose_name = _("foyer")
        verbose_name_plural = _("foyers")

    def __str__(self) -> str:
        return self.nom

    @property
    def est_personnel(self) -> bool:
        return self.personne_id is not None


class Adhesion(ModeleDeFoyer):
    """Appartenance d'un utilisateur à un foyer, avec son rôle.

    Chaque utilisateur a au plus un foyer principal, ouvert par défaut à la connexion.
    """

    foyer = models.ForeignKey(
        Foyer, verbose_name=_("foyer"), on_delete=models.CASCADE, related_name="adhesions"
    )
    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("utilisateur"),
        on_delete=models.CASCADE,
        related_name="adhesions",
    )
    role = models.CharField(_("rôle"), max_length=20, choices=Role.choices, default=Role.MEMBRE)
    est_principal = models.BooleanField(_("foyer principal"), default=False)

    class Meta:
        verbose_name = _("adhésion")
        verbose_name_plural = _("adhésions")
        constraints = [
            models.UniqueConstraint(
                fields=["utilisateur", "foyer"], name="adhesion_unique_par_foyer"
            ),
            models.UniqueConstraint(
                fields=["utilisateur"],
                condition=Q(est_principal=True),
                name="adhesion_un_seul_foyer_principal",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.utilisateur} – {self.foyer} ({self.get_role_display()})"

    def a_au_moins(self, role: str) -> bool:
        return NIVEAU_PAR_ROLE[self.role] >= NIVEAU_PAR_ROLE[role]


class RequeteInvitation(RequeteDeFoyer):
    def en_attente(self) -> Self:
        return self.filter(
            acceptee_le__isnull=True, revoquee_le__isnull=True, expire_le__gt=timezone.now()
        )


GestionnaireInvitation = models.Manager.from_queryset(RequeteInvitation)


class Invitation(ModeleDeFoyer):
    foyer = models.ForeignKey(
        Foyer, verbose_name=_("foyer"), on_delete=models.CASCADE, related_name="invitations"
    )
    email = models.EmailField(_("adresse e-mail"))
    role = models.CharField(_("rôle"), max_length=20, choices=Role.choices, default=Role.MEMBRE)
    # Seule l'empreinte SHA-256 du jeton est conservée : une fuite de la base
    # ne permet pas d'accepter une invitation.
    empreinte_jeton = models.CharField(max_length=64, unique=True, editable=False)
    invite_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("invité par"),
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    expire_le = models.DateTimeField(_("expire le"))
    acceptee_le = models.DateTimeField(_("acceptée le"), null=True, blank=True)
    revoquee_le = models.DateTimeField(_("révoquée le"), null=True, blank=True)

    objects = GestionnaireInvitation()  # type: ignore[misc]

    class Meta:
        verbose_name = _("invitation")
        verbose_name_plural = _("invitations")
        ordering = ["-cree_le"]

    def __str__(self) -> str:
        return f"{self.email} → {self.foyer}"

    @property
    def est_en_attente(self) -> bool:
        return (
            self.acceptee_le is None
            and self.revoquee_le is None
            and self.expire_le > timezone.now()
        )
