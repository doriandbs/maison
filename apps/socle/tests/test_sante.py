from unittest import mock

import pytest
from django.core.management import CommandError, call_command
from django.test import RequestFactory

from apps.socle.reseau import ip_cliente


@pytest.mark.django_db
def test_sante_repond_ok(client):
    reponse = client.get("/sante/")

    assert reponse.status_code == 200
    assert reponse.json() == {"etat": "ok"}


def test_sante_repond_503_si_la_base_est_injoignable(client):
    with mock.patch("apps.socle.views.base_joignable", return_value=False):
        reponse = client.get("/sante/")

    assert reponse.status_code == 503


@pytest.mark.django_db
def test_commande_verifier_sante():
    call_command("verifier_sante")


@pytest.mark.django_db
def test_commande_verifier_sante_echoue_si_migrations_en_attente():
    cible = "apps.socle.management.commands.verifier_sante.migrations_en_attente"
    with mock.patch(cible, return_value=["foyers.0002_x"]), pytest.raises(CommandError):
        call_command("verifier_sante")


def test_ip_cliente_lit_l_en_tete_du_proxy():
    requete = RequestFactory().get("/", HTTP_X_FORWARDED_FOR="203.0.113.7, 10.0.0.1")

    assert ip_cliente(requete) == "203.0.113.7"


def test_ip_cliente_sans_proxy():
    requete = RequestFactory().get("/", REMOTE_ADDR="198.51.100.2")

    assert ip_cliente(requete) == "198.51.100.2"
