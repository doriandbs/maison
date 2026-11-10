import re

import pytest
from django.core import mail
from django.db import IntegrityError
from django.urls import reverse

from apps.utilisateurs.models import Utilisateur

from .fabriques import MOT_DE_PASSE, FabriqueUtilisateur

pytestmark = pytest.mark.django_db

DONNEES_INSCRIPTION = {
    "first_name": "Alice",
    "email": "Alice@Example.org",
    "password1": MOT_DE_PASSE,
    "password2": MOT_DE_PASSE,
}


def _lien(message: mail.EmailMessage) -> str:
    return re.search(r"https?://\S+", message.body).group(0)


def _connecter(client, email: str, mot_de_passe: str = MOT_DE_PASSE):
    return client.post(
        reverse("utilisateurs:connexion"), {"username": email, "password": mot_de_passe}
    )


class TestInscription:
    def test_cree_un_compte_inactif_et_envoie_le_lien(self, client):
        reponse = client.post(reverse("utilisateurs:inscription"), DONNEES_INSCRIPTION)

        assert reponse.status_code == 302
        utilisateur = Utilisateur.objects.get()
        assert utilisateur.email == "alice@example.org"
        assert not utilisateur.is_active
        assert mail.outbox[0].to == ["alice@example.org"]

    def test_le_lien_active_le_compte_une_seule_fois(self, client):
        client.post(reverse("utilisateurs:inscription"), DONNEES_INSCRIPTION)
        lien = _lien(mail.outbox[0])

        assert client.get(lien).status_code == 302
        assert Utilisateur.objects.get().is_active
        assert client.get(lien).status_code == 400

    def test_lien_falsifie_refuse(self, client):
        client.post(reverse("utilisateurs:inscription"), DONNEES_INSCRIPTION)
        lien = _lien(mail.outbox[0]).rstrip("/")[:-3] + "abc/"

        assert client.get(lien).status_code == 400
        assert not Utilisateur.objects.get().is_active

    def test_adresse_deja_prise_quelle_que_soit_la_casse(self, client):
        FabriqueUtilisateur(email="alice@example.org")

        reponse = client.post(reverse("utilisateurs:inscription"), DONNEES_INSCRIPTION)

        assert reponse.status_code == 200
        assert Utilisateur.objects.count() == 1
        assert mail.outbox == []

    def test_mot_de_passe_faible_refuse(self, client):
        donnees = DONNEES_INSCRIPTION | {"password1": "12345678", "password2": "12345678"}

        reponse = client.post(reverse("utilisateurs:inscription"), donnees)

        assert reponse.status_code == 200
        assert not Utilisateur.objects.exists()

    def test_inscription_fermee(self, client, settings):
        settings.INSCRIPTION_OUVERTE = False

        assert client.get(reverse("utilisateurs:inscription")).status_code == 404
        reponse = client.post(reverse("utilisateurs:inscription"), DONNEES_INSCRIPTION)
        assert reponse.status_code == 404
        assert not Utilisateur.objects.exists()

    def test_limitation_de_debit(self, client, settings):
        settings.RATELIMIT_ENABLE = True
        url = reverse("utilisateurs:inscription")

        codes = [client.post(url, {}).status_code for _ in range(11)]

        assert codes[:10] == [200] * 10
        assert codes[10] == 429


class TestConnexion:
    def test_connexion_insensible_a_la_casse(self, client):
        FabriqueUtilisateur(email="alice@example.org")

        reponse = _connecter(client, " ALICE@example.org ")

        assert reponse.status_code == 302
        assert "_auth_user_id" in client.session

    def test_compte_non_active_refuse(self, client):
        FabriqueUtilisateur(email="alice@example.org", is_active=False)

        reponse = _connecter(client, "alice@example.org")

        assert reponse.status_code == 200
        assert "_auth_user_id" not in client.session

    def test_verrouillage_apres_cinq_echecs(self, client, settings):
        settings.AXES_ENABLED = True
        FabriqueUtilisateur(email="alice@example.org")
        for _ in range(5):
            _connecter(client, "alice@example.org", "mauvais")

        reponse = _connecter(client, "alice@example.org")

        assert reponse.status_code == 429
        assert "_auth_user_id" not in client.session

    def test_deconnexion_uniquement_en_post(self, client):
        client.force_login(FabriqueUtilisateur())

        assert client.get(reverse("utilisateurs:deconnexion")).status_code == 405
        client.post(reverse("utilisateurs:deconnexion"))
        assert "_auth_user_id" not in client.session


class TestMotDePasseOublie:
    def test_envoie_un_lien_qui_permet_de_changer_le_mot_de_passe(self, client):
        utilisateur = FabriqueUtilisateur(email="alice@example.org")

        client.post(reverse("utilisateurs:mot_de_passe_oublie"), {"email": "alice@example.org"})
        formulaire = client.get(_lien(mail.outbox[0]), follow=True)
        nouveau = "encore-un-autre-secret-77"
        client.post(
            formulaire.request["PATH_INFO"], {"new_password1": nouveau, "new_password2": nouveau}
        )

        utilisateur.refresh_from_db()
        assert utilisateur.check_password(nouveau)

    def test_adresse_inconnue_meme_reponse_sans_email(self, client):
        reponse = client.post(
            reverse("utilisateurs:mot_de_passe_oublie"), {"email": "inconnu@example.org"}
        )

        assert reponse.status_code == 302
        assert mail.outbox == []


def test_unicite_de_l_email_garantie_en_base():
    FabriqueUtilisateur(email="alice@example.org")

    with pytest.raises(IntegrityError):
        Utilisateur.objects.bulk_create([Utilisateur(email="ALICE@example.org")])


def test_creation_d_un_superutilisateur():
    admin = Utilisateur.objects.create_superuser("Admin@Example.org", MOT_DE_PASSE)

    assert admin.email == "admin@example.org"
    assert admin.is_staff and admin.is_superuser
