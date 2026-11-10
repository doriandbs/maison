import re

import pytest
from django.core.management import call_command
from django.urls import reverse
from django_otp.oath import TOTP
from django_otp.plugins.otp_static.models import StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.foyers.models import Role
from apps.foyers.tests.fabriques import FabriqueAdhesion
from apps.utilisateurs import double_auth

from .fabriques import MOT_DE_PASSE

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def double_auth_obligatoire(settings):
    settings.DOUBLE_AUTH_OBLIGATOIRE = True


@pytest.fixture
def membre():
    return FabriqueAdhesion(role=Role.PROPRIETAIRE, est_principal=True, foyer__nom="Chez nous")


@pytest.fixture
def equipe(membre):
    """Le membre a déjà configuré son application ; renvoie ses codes de secours."""
    appareil = double_auth.preparer_application(membre.utilisateur)
    return double_auth.confirmer_application(appareil, _code(appareil))


def _code(appareil: TOTPDevice) -> str:
    totp = TOTP(appareil.bin_key, appareil.step, appareil.t0, appareil.digits, appareil.drift)
    return f"{totp.token():0{appareil.digits}d}"


def _code_suivant(appareil: TOTPDevice) -> str:
    """Code de la période suivante, encore accepté (dérive d'horloge tolérée)."""
    totp = TOTP(appareil.bin_key, appareil.step, appareil.t0, appareil.digits, appareil.drift)
    totp.time = totp.time + appareil.step
    return f"{totp.token():0{appareil.digits}d}"


def _mot_de_passe(client, utilisateur, **suite):
    return client.post(
        reverse("utilisateurs:connexion"),
        {"username": utilisateur.email, "password": MOT_DE_PASSE, **suite},
    )


def _bloque(reponse) -> bool:
    """La page est refusée ET renvoie vers l'étape du code (pas seulement « une redirection »)."""
    etapes = (reverse("utilisateurs:verification"), reverse("utilisateurs:activer_double_auth"))
    return reponse.status_code == 302 and reponse.url.startswith(etapes)


def _appareil(utilisateur) -> TOTPDevice:
    return TOTPDevice.objects.get(user=utilisateur, confirmed=True)


class TestMotDePasseSeul:
    def test_ne_donne_acces_a_rien(self, client, membre, equipe):
        _mot_de_passe(client, membre.utilisateur)

        for url in ["/", reverse("banque:comptes"), reverse("documents:liste")]:
            reponse = client.get(url)
            assert reponse.status_code == 302
            assert reponse.url.startswith(reverse("utilisateurs:verification"))

    def test_ne_revele_pas_le_foyer(self, client, membre, equipe):
        _mot_de_passe(client, membre.utilisateur)

        page = client.get(reverse("utilisateurs:verification")).content.decode()

        assert "Chez nous" not in page

    def test_un_compte_sans_application_doit_la_configurer(self, client, membre):
        _mot_de_passe(client, membre.utilisateur)

        reponse = client.get(reverse("banque:operations"))

        assert reponse.url.startswith(reverse("utilisateurs:activer_double_auth"))
        assert "next=%2Foperations%2F" in reponse.url


class TestActivation:
    def test_qr_code_puis_codes_de_secours_puis_acces(self, client, membre):
        _mot_de_passe(client, membre.utilisateur)
        page = client.get(reverse("utilisateurs:activer_double_auth"))
        assert "<svg" in page.content.decode()
        appareil = TOTPDevice.objects.get(user=membre.utilisateur, confirmed=False)

        reponse = client.post(
            reverse("utilisateurs:activer_double_auth"), {"code": _code(appareil)}
        )
        codes = client.get(reponse.url)
        affiches = re.findall(r'<li class="select-all">(\w+)</li>', codes.content.decode())

        assert len(affiches) == double_auth.NOMBRE_CODES_SECOURS
        assert client.get(reverse("utilisateurs:codes_secours")).status_code == 302  # une fois
        assert client.get("/").status_code == 200

    def test_mauvais_code_n_active_rien(self, client, membre):
        _mot_de_passe(client, membre.utilisateur)
        client.get(reverse("utilisateurs:activer_double_auth"))

        client.post(reverse("utilisateurs:activer_double_auth"), {"code": "000000"})

        assert not double_auth.est_configuree(membre.utilisateur)
        assert _bloque(client.get("/"))

    def test_impossible_de_remplacer_une_application_sans_le_code(self, client, membre, equipe):
        _mot_de_passe(client, membre.utilisateur)

        reponse = client.get(reverse("utilisateurs:activer_double_auth"))

        assert reponse.url.startswith(reverse("utilisateurs:verification"))


class TestVerification:
    def test_code_de_l_application(self, client, membre, equipe):
        _mot_de_passe(client, membre.utilisateur)

        reponse = client.post(
            reverse("utilisateurs:verification") + "?next=/operations/",
            {"code": _code_suivant(_appareil(membre.utilisateur)), "next": "/operations/"},
        )

        assert reponse.url == "/operations/"
        assert client.get("/").status_code == 200

    def test_un_code_ne_sert_qu_une_fois(self, client, membre, equipe):
        code = _code_suivant(_appareil(membre.utilisateur))
        _mot_de_passe(client, membre.utilisateur)
        client.post(reverse("utilisateurs:verification"), {"code": code})
        client.post(reverse("utilisateurs:deconnexion"))

        _mot_de_passe(client, membre.utilisateur)
        client.post(reverse("utilisateurs:verification"), {"code": code})

        assert _bloque(client.get("/"))

    def test_les_essais_sont_freines(self, client, membre, equipe):
        _mot_de_passe(client, membre.utilisateur)
        client.post(reverse("utilisateurs:verification"), {"code": "000000"})

        reponse = client.post(
            reverse("utilisateurs:verification"),
            {"code": _code_suivant(_appareil(membre.utilisateur))},
        )

        assert "Trop d&#x27;essais" in reponse.content.decode()
        assert _bloque(client.get("/"))

    def test_code_de_secours_a_usage_unique(self, client, membre, equipe):
        _mot_de_passe(client, membre.utilisateur)
        client.post(reverse("utilisateurs:verification"), {"code": equipe[0].upper()})
        assert client.get("/").status_code == 200
        client.post(reverse("utilisateurs:deconnexion"))

        _mot_de_passe(client, membre.utilisateur)
        client.post(reverse("utilisateurs:verification"), {"code": equipe[0]})

        assert _bloque(client.get("/"))
        assert StaticToken.objects.filter(device__user=membre.utilisateur).count() == 9

    def test_le_lien_suivant_ne_sort_pas_du_site(self, client, membre, equipe):
        _mot_de_passe(client, membre.utilisateur)

        reponse = client.post(
            reverse("utilisateurs:verification"),
            {
                "code": _code_suivant(_appareil(membre.utilisateur)),
                "next": "https://pirate.example",
            },
        )

        assert reponse.url == reverse("accueil")


class TestAppareilDeConfiance:
    def _se_souvenir(self, client, utilisateur):
        _mot_de_passe(client, utilisateur)
        client.post(
            reverse("utilisateurs:verification"),
            {"code": _code_suivant(_appareil(utilisateur)), "memoriser": "on"},
        )
        client.post(reverse("utilisateurs:deconnexion"))

    def test_le_code_n_est_plus_demande(self, client, membre, equipe):
        self._se_souvenir(client, membre.utilisateur)

        _mot_de_passe(client, membre.utilisateur)

        assert client.get("/").status_code == 200

    def test_le_mot_de_passe_reste_exige(self, client, membre, equipe):
        self._se_souvenir(client, membre.utilisateur)

        assert client.get("/").url.startswith(reverse("utilisateurs:connexion"))

    def test_le_cookie_ne_vaut_que_pour_son_compte(self, client, membre, equipe):
        self._se_souvenir(client, membre.utilisateur)
        autre = FabriqueAdhesion(role=Role.MEMBRE, est_principal=True)
        appareil = double_auth.preparer_application(autre.utilisateur)
        double_auth.confirmer_application(appareil, _code(appareil))

        _mot_de_passe(client, autre.utilisateur)

        assert _bloque(client.get("/"))

    def test_oublier_les_appareils(self, client, membre, equipe):
        self._se_souvenir(client, membre.utilisateur)
        double_auth.oublier_appareils(membre.utilisateur)

        _mot_de_passe(client, membre.utilisateur)

        assert _bloque(client.get("/"))


class TestMonCompte:
    def _verifie(self, client, utilisateur):
        _mot_de_passe(client, utilisateur)
        client.post(
            reverse("utilisateurs:verification"), {"code": _code_suivant(_appareil(utilisateur))}
        )

    def test_changer_de_telephone_exige_le_mot_de_passe(self, client, membre, equipe):
        self._verifie(client, membre.utilisateur)

        client.post(reverse("utilisateurs:changer_telephone"), {"mot_de_passe": "mauvais"})
        assert double_auth.est_configuree(membre.utilisateur)

        reponse = client.post(
            reverse("utilisateurs:changer_telephone"), {"mot_de_passe": MOT_DE_PASSE}
        )
        assert reponse.url == reverse("utilisateurs:activer_double_auth")
        assert not double_auth.est_configuree(membre.utilisateur)
        assert double_auth.codes_secours_restants(membre.utilisateur) == 0

    def test_nouveaux_codes_de_secours(self, client, membre, equipe):
        self._verifie(client, membre.utilisateur)

        client.post(reverse("utilisateurs:codes_secours"))

        restants = set(
            StaticToken.objects.filter(device__user=membre.utilisateur).values_list(
                "token", flat=True
            )
        )
        assert len(restants) == 10 and not restants & set(equipe)


class TestAdmin:
    def test_la_connexion_de_l_admin_passe_par_celle_du_site(self, client):
        reponse = client.get(reverse("admin:login"))

        assert reponse.url.startswith(reverse("utilisateurs:connexion"))

    def test_un_compte_admin_sans_code_n_entre_pas(self, client, membre, equipe):
        membre.utilisateur.is_staff = membre.utilisateur.is_superuser = True
        membre.utilisateur.save()
        _mot_de_passe(client, membre.utilisateur)

        assert client.get(reverse("admin:index")).status_code == 302

        client.post(
            reverse("utilisateurs:verification"),
            {"code": _code_suivant(_appareil(membre.utilisateur))},
        )
        assert client.get(reverse("admin:index")).status_code == 200


def test_commande_de_secours(membre, equipe):
    call_command("retirer_double_auth", membre.utilisateur.email.upper())

    assert not double_auth.est_configuree(membre.utilisateur)
    assert double_auth.codes_secours_restants(membre.utilisateur) == 0
