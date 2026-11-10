from __future__ import annotations

from typing import Any

from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _


class GestionnaireUtilisateur(BaseUserManager["Utilisateur"]):
    use_in_migrations = True

    def _creer(self, email: str, password: str | None, **champs: Any) -> Utilisateur:
        if not email:
            raise ValueError("L'adresse e-mail est obligatoire.")
        utilisateur = self.model(email=email.strip().lower(), **champs)
        utilisateur.set_password(password)
        utilisateur.save(using=self._db)
        return utilisateur

    def create_user(self, email: str, password: str | None = None, **champs: Any) -> Utilisateur:
        champs.setdefault("is_staff", False)
        champs.setdefault("is_superuser", False)
        return self._creer(email, password, **champs)

    def create_superuser(
        self, email: str, password: str | None = None, **champs: Any
    ) -> Utilisateur:
        champs["is_staff"] = True
        champs["is_superuser"] = True
        return self._creer(email, password, **champs)


class Utilisateur(AbstractUser):
    """Compte identifié par son e-mail, toujours stocké en minuscules.

    Les champs hérités de Django (`first_name`, `is_active`…) gardent leur nom d'origine.
    """

    username = None  # type: ignore[assignment]
    email = models.EmailField(_("adresse e-mail"), unique=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = GestionnaireUtilisateur()  # type: ignore[misc,assignment]

    class Meta:
        verbose_name = _("utilisateur")
        verbose_name_plural = _("utilisateurs")
        constraints = [
            models.UniqueConstraint(Lower("email"), name="utilisateur_email_unique_sans_casse"),
        ]

    def __str__(self) -> str:
        return self.get_full_name() or self.email
