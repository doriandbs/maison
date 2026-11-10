from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from .models import Utilisateur


class GenerateurJetonActivation(PasswordResetTokenGenerator):
    """Jeton signé, valable `PASSWORD_RESET_TIMEOUT`, invalidé dès que le compte est activé."""

    def _make_hash_value(self, user: Utilisateur, timestamp: int) -> str:
        return f"{user.pk}{timestamp}{user.is_active}"


generateur_jeton_activation = GenerateurJetonActivation()


def identifiants_activation(utilisateur: Utilisateur) -> tuple[str, str]:
    uid = urlsafe_base64_encode(force_bytes(utilisateur.pk))
    return uid, generateur_jeton_activation.make_token(utilisateur)


def envoyer_email_activation(utilisateur: Utilisateur, url_activation: str) -> None:
    contexte = {"utilisateur": utilisateur, "url_activation": url_activation}
    send_mail(
        subject=render_to_string("utilisateurs/emails/activation_sujet.txt", contexte).strip(),
        message=render_to_string("utilisateurs/emails/activation.txt", contexte),
        from_email=None,
        recipient_list=[utilisateur.email],
    )


def activer_compte(uidb64: str, jeton: str) -> Utilisateur | None:
    try:
        pk = force_str(urlsafe_base64_decode(uidb64))
        utilisateur = Utilisateur.objects.get(pk=pk)
    except (ValueError, OverflowError, Utilisateur.DoesNotExist):
        return None
    if not generateur_jeton_activation.check_token(utilisateur, jeton):
        return None
    utilisateur.is_active = True
    utilisateur.save(update_fields=["is_active"])
    return utilisateur
