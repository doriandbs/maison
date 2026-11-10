from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.utilisateurs.models import Utilisateur

from .models import Adhesion, Foyer, Invitation, Role
from .signaux import foyer_cree

DUREE_INVITATION = timedelta(days=7)


class ErreurFoyer(Exception):
    """Règle métier violée ; le message est affichable tel quel à l'utilisateur."""


def empreinte(jeton: str) -> str:
    return hashlib.sha256(jeton.encode()).hexdigest()


def _a_un_foyer_principal(utilisateur: Utilisateur) -> bool:
    return Adhesion.objects.filter(utilisateur=utilisateur, est_principal=True).exists()


@transaction.atomic
def creer_foyer(*, utilisateur: Utilisateur, nom: str) -> Foyer:
    foyer = Foyer.objects.create(nom=nom, cree_par=utilisateur)
    Adhesion.objects.create(
        foyer=foyer,
        utilisateur=utilisateur,
        role=Role.PROPRIETAIRE,
        est_principal=not _a_un_foyer_principal(utilisateur),
    )
    foyer_cree.send(sender=Foyer, foyer=foyer)
    return foyer


@transaction.atomic
def definir_foyer_principal(adhesion: Adhesion) -> None:
    Adhesion.objects.filter(utilisateur=adhesion.utilisateur, est_principal=True).update(
        est_principal=False
    )
    adhesion.est_principal = True
    adhesion.save(update_fields=["est_principal", "modifie_le"])


@transaction.atomic
def inviter(
    *, foyer: Foyer, email: str, role: str, invite_par: Utilisateur
) -> tuple[Invitation, str]:
    """Crée l'invitation et renvoie le jeton en clair, qui n'est stocké nulle part."""
    email = email.strip().lower()
    if role == Role.PROPRIETAIRE:
        raise ErreurFoyer(_("On ne peut pas inviter directement un propriétaire."))
    if Adhesion.objects.du_foyer(foyer).filter(utilisateur__email=email).exists():
        raise ErreurFoyer(_("Cette personne est déjà membre du foyer."))
    Invitation.objects.du_foyer(foyer).en_attente().filter(email=email).update(
        revoquee_le=timezone.now()
    )
    jeton = secrets.token_urlsafe(32)
    invitation = Invitation.objects.create(
        foyer=foyer,
        email=email,
        role=role,
        empreinte_jeton=empreinte(jeton),
        invite_par=invite_par,
        expire_le=timezone.now() + DUREE_INVITATION,
    )
    return invitation, jeton


def envoyer_email_invitation(invitation: Invitation, url_acceptation: str) -> None:
    contexte = {"invitation": invitation, "url_acceptation": url_acceptation}
    send_mail(
        subject=render_to_string("foyers/emails/invitation_sujet.txt", contexte).strip(),
        message=render_to_string("foyers/emails/invitation.txt", contexte),
        from_email=None,
        recipient_list=[invitation.email],
    )


def revoquer_invitation(invitation: Invitation) -> None:
    invitation.revoquee_le = timezone.now()
    invitation.save(update_fields=["revoquee_le", "modifie_le"])


@transaction.atomic
def accepter_invitation(*, invitation: Invitation, utilisateur: Utilisateur) -> Adhesion:
    invitation = Invitation.objects.select_for_update().get(pk=invitation.pk)
    if not invitation.est_en_attente:
        raise ErreurFoyer(_("Cette invitation n'est plus valide."))
    if invitation.email != utilisateur.email.lower():
        raise ErreurFoyer(_("Cette invitation est destinée à une autre adresse e-mail."))
    adhesion, _creee = Adhesion.objects.get_or_create(
        foyer=invitation.foyer,
        utilisateur=utilisateur,
        defaults={
            "role": invitation.role,
            "est_principal": not _a_un_foyer_principal(utilisateur),
        },
    )
    invitation.acceptee_le = timezone.now()
    invitation.save(update_fields=["acceptee_le", "modifie_le"])
    return adhesion


def _verifier_droit_de_gestion(par: Adhesion, cible: Adhesion, nouveau_role: str | None) -> None:
    if par.foyer_id != cible.foyer_id or not par.a_au_moins(Role.ADMINISTRATEUR):
        raise ErreurFoyer(_("Vous n'avez pas le droit de gérer les membres de ce foyer."))
    touche_un_proprietaire = Role.PROPRIETAIRE in (cible.role, nouveau_role)
    if touche_un_proprietaire and par.role != Role.PROPRIETAIRE:
        raise ErreurFoyer(_("Seul un propriétaire peut gérer les propriétaires."))


def _verifier_qu_il_reste_un_proprietaire(cible: Adhesion) -> None:
    if cible.role != Role.PROPRIETAIRE:
        return
    autres = (
        Adhesion.objects.select_for_update()
        .filter(foyer_id=cible.foyer_id, role=Role.PROPRIETAIRE)
        .exclude(pk=cible.pk)
    )
    if not autres.exists():
        raise ErreurFoyer(_("Un foyer doit toujours garder au moins un propriétaire."))


@transaction.atomic
def changer_role(*, adhesion: Adhesion, role: str, par: Adhesion) -> None:
    if role not in Role.values:
        raise ErreurFoyer(_("Rôle inconnu."))
    _verifier_droit_de_gestion(par, adhesion, role)
    if role != Role.PROPRIETAIRE:
        _verifier_qu_il_reste_un_proprietaire(adhesion)
    adhesion.role = role
    adhesion.save(update_fields=["role", "modifie_le"])


@transaction.atomic
def retirer_membre(*, adhesion: Adhesion, par: Adhesion) -> None:
    """Retire un membre du foyer ; chacun peut se retirer lui-même."""
    if adhesion.pk != par.pk:
        _verifier_droit_de_gestion(par, adhesion, None)
    _verifier_qu_il_reste_un_proprietaire(adhesion)
    utilisateur, etait_principal = adhesion.utilisateur, adhesion.est_principal
    adhesion.delete()
    if etait_principal:
        suivante = Adhesion.objects.filter(utilisateur=utilisateur).order_by("cree_le").first()
        if suivante is not None:
            definir_foyer_principal(suivante)
