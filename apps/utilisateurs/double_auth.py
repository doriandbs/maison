"""Double authentification : application TOTP, codes de secours, appareils de confiance.

Le stockage et la vérification des codes (fenêtre de tolérance, rejeu, freinage des essais)
sont délégués à django-otp ; ce module décide qui doit fournir un code et quand.
"""

from __future__ import annotations

import time
from base64 import b32encode
from datetime import timedelta
from typing import TYPE_CHECKING

import segno
from django.conf import settings
from django.core import signing
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.utils import timezone
from django_otp import login as marquer_verifie
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

if TYPE_CHECKING:
    from django_otp.models import Device

    from .models import Utilisateur

NOMBRE_CODES_SECOURS = 10
SEL_APPAREIL = "maison.appareil-de-confiance"


def _nom_cookie(request: HttpRequest) -> str:
    # Le préfixe __Host- interdit qu'un sous-domaine pose ou lise ce cookie (HTTPS seulement).
    return "__Host-maison-appareil" if request.is_secure() else "maison-appareil"


# --- État -------------------------------------------------------------------


def est_verifie(utilisateur: object) -> bool:
    """Code saisi pendant cette session (méthode ajoutée à l'utilisateur par OTPMiddleware)."""
    verification = getattr(utilisateur, "is_verified", None)
    return bool(verification and verification())


def application(utilisateur: Utilisateur) -> TOTPDevice | None:
    return TOTPDevice.objects.filter(user=utilisateur, confirmed=True).first()


def est_configuree(utilisateur: Utilisateur) -> bool:
    return TOTPDevice.objects.filter(user=utilisateur, confirmed=True).exists()


def acces_complet(request: HttpRequest) -> bool:
    """La session donne-t-elle accès aux données ? Mot de passe ET, si exigé, code."""
    utilisateur = request.user
    if not utilisateur.is_authenticated:
        return False
    if est_verifie(utilisateur):
        return True
    return not settings.DOUBLE_AUTH_OBLIGATOIRE and not est_configuree(utilisateur)


def codes_secours_restants(utilisateur: Utilisateur) -> int:
    return StaticToken.objects.filter(device__user=utilisateur, device__confirmed=True).count()


# --- Activation ---------------------------------------------------------------


def preparer_application(utilisateur: Utilisateur) -> TOTPDevice:
    """Appareil en attente de confirmation : réutilisé tant que le QR code n'est pas validé."""
    attente = TOTPDevice.objects.filter(user=utilisateur, confirmed=False).first()
    return attente or TOTPDevice.objects.create(
        user=utilisateur, name="Application", confirmed=False
    )


def qr_code_svg(appareil: TOTPDevice) -> str:
    return segno.make(appareil.config_url, error="m").svg_inline(scale=5, border=2)


def cle_lisible(appareil: TOTPDevice) -> str:
    """Clé à saisir à la main si le QR code ne peut pas être scanné : « ABCD EFGH … »."""
    cle = b32encode(appareil.bin_key).decode().rstrip("=")
    return " ".join(cle[i : i + 4] for i in range(0, len(cle), 4))


@transaction.atomic
def confirmer_application(appareil: TOTPDevice, code: str) -> list[str] | None:
    """Valide le premier code ; renvoie alors les codes de secours (affichés une seule fois)."""
    if not appareil.verify_token(_chiffres(code)):
        return None
    TOTPDevice.objects.filter(user=appareil.user).exclude(pk=appareil.pk).delete()
    appareil.confirmed = True
    appareil.save(update_fields=["confirmed"])
    return generer_codes_secours(appareil.user)


@transaction.atomic
def generer_codes_secours(utilisateur: Utilisateur) -> list[str]:
    """Remplace tous les codes de secours : les anciens cessent de fonctionner."""
    appareil, _ = StaticDevice.objects.get_or_create(
        user=utilisateur, name="Codes de secours", defaults={"confirmed": True}
    )
    appareil.token_set.all().delete()
    codes = [StaticToken.random_token() for _ in range(NOMBRE_CODES_SECOURS)]
    StaticToken.objects.bulk_create(StaticToken(device=appareil, token=code) for code in codes)
    return codes


@transaction.atomic
def retirer(utilisateur: Utilisateur) -> None:
    """Supprime application et codes de secours (téléphone perdu, changement de téléphone)."""
    TOTPDevice.objects.filter(user=utilisateur).delete()
    StaticDevice.objects.filter(user=utilisateur).delete()
    oublier_appareils(utilisateur)


# --- Connexion ----------------------------------------------------------------


def _chiffres(code: str) -> str:
    return "".join(code.split())


def verifier_code(utilisateur: Utilisateur, code: str) -> Device | None:
    """Code de l'application (6 chiffres) ou code de secours (consommé s'il est valide)."""
    code = _chiffres(code).lower()
    appareils: list[Device] = [
        *TOTPDevice.objects.filter(user=utilisateur, confirmed=True),
        *StaticDevice.objects.filter(user=utilisateur, confirmed=True),
    ]
    for appareil in appareils:
        if appareil.verify_is_allowed()[0] and appareil.verify_token(code):
            return appareil
    return None


def essais_bloques(utilisateur: Utilisateur) -> bool:
    """Vrai si trop d'erreurs récentes : l'utilisateur doit patienter avant de réessayer."""
    appareil = application(utilisateur)
    return appareil is not None and not appareil.verify_is_allowed()[0]


def valider_session(request: HttpRequest, appareil: Device) -> None:
    marquer_verifie(request, appareil)


# --- Appareils de confiance ---------------------------------------------------


def memoriser_appareil(request: HttpRequest, reponse: HttpResponse) -> None:
    jeton = signing.dumps({"u": request.user.pk, "t": int(time.time())}, salt=SEL_APPAREIL)
    reponse.set_cookie(
        _nom_cookie(request),
        jeton,
        max_age=settings.DUREE_APPAREIL_DE_CONFIANCE,
        secure=request.is_secure(),
        httponly=True,
        samesite="Lax",
    )


def appareil_de_confiance(request: HttpRequest, utilisateur: Utilisateur) -> bool:
    jeton = request.COOKIES.get(_nom_cookie(request))
    if not jeton:
        return False
    try:
        contenu = signing.loads(
            jeton, salt=SEL_APPAREIL, max_age=settings.DUREE_APPAREIL_DE_CONFIANCE
        )
    except signing.BadSignature:
        return False
    if contenu.get("u") != utilisateur.pk:
        return False
    revoque = utilisateur.appareils_revoques_le
    return revoque is None or contenu.get("t", 0) > revoque.timestamp()


def oublier_appareils(utilisateur: Utilisateur) -> None:
    """Tous les appareils mémorisés devront de nouveau fournir un code."""
    # +1 s : un cookie émis dans la même seconde que la révocation est aussi révoqué.
    utilisateur.appareils_revoques_le = timezone.now() + timedelta(seconds=1)
    utilisateur.save(update_fields=["appareils_revoques_le"])
