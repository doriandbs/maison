from datetime import date
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.documents.models import Document, TypeDocument
from apps.foyers.models import Role
from apps.foyers.tests.fabriques import FabriqueAdhesion

from .fabriques import PDF_MINIMAL, PNG_MINIMAL, FabriqueDocument

pytestmark = pytest.mark.django_db


@pytest.fixture
def alice(client):
    """Membre du foyer A, connectée."""
    adhesion = FabriqueAdhesion(role=Role.MEMBRE, est_principal=True)
    client.force_login(adhesion.utilisateur)
    return adhesion


@pytest.fixture
def document_b():
    """Document d'un autre foyer, qu'Alice ne doit jamais atteindre."""
    return FabriqueDocument(titre="Document secret", emetteur="Émetteur secret")


def _pdf(nom: str = "facture.pdf") -> SimpleUploadedFile:
    return SimpleUploadedFile(nom, PDF_MINIMAL, content_type="application/pdf")


def _donnees(**surcharges):
    return {
        "titre": "Facture d'électricité",
        "type": TypeDocument.FACTURE,
        "emetteur": "Fournisseur",
        "date": "2026-03-01",
        "montant": "84.20",
        "echeance": "2026-03-20",
        "fichier": _pdf(),
    } | surcharges


ROUTES_SUR_UN_DOCUMENT = [
    "documents:document",
    "documents:modifier",
    "documents:supprimer",
    "documents:paiement",
    "documents:fichier",
]


class TestIsolationEntreFoyers:
    @pytest.mark.parametrize("route", ROUTES_SUR_UN_DOCUMENT)
    def test_le_document_d_un_autre_foyer_est_introuvable(self, client, alice, document_b, route):
        url = reverse(route, args=[document_b.pk])

        codes = {client.get(url).status_code, client.post(url, _donnees()).status_code}

        assert codes <= {404, 405}
        assert 404 in codes

    def test_rien_n_a_change_dans_l_autre_foyer(self, client, alice, document_b, medias):
        for route in ROUTES_SUR_UN_DOCUMENT:
            client.post(reverse(route, args=[document_b.pk]), _donnees(titre="piraté"))

        document_b.refresh_from_db()
        assert document_b.titre == "Document secret" and document_b.paye_le is None
        assert (medias / document_b.fichier.name).exists()

    def test_la_liste_ne_montre_que_le_foyer_courant(self, client, alice, document_b):
        reponse = client.get(reverse("documents:liste"), {"recherche": "secret"})

        assert list(reponse.context["documents"]) == []
        assert "Document secret" not in reponse.content.decode()


class TestLectureSeule:
    @pytest.mark.parametrize("route", ["documents:ajouter", *ROUTES_SUR_UN_DOCUMENT[1:4]])
    def test_un_lecteur_ne_peut_rien_modifier(self, client, route):
        lecteur = FabriqueAdhesion(role=Role.LECTEUR)
        document = FabriqueDocument(foyer=lecteur.foyer)
        client.force_login(lecteur.utilisateur)
        arguments = [] if route == "documents:ajouter" else [document.pk]

        assert client.post(reverse(route, args=arguments), _donnees()).status_code == 403

    def test_un_lecteur_consulte_et_ouvre_les_fichiers(self, client):
        lecteur = FabriqueAdhesion(role=Role.LECTEUR)
        document = FabriqueDocument(foyer=lecteur.foyer)
        client.force_login(lecteur.utilisateur)

        page = client.get(reverse("documents:document", args=[document.pk])).content.decode()
        fichier = client.get(reverse("documents:fichier", args=[document.pk]))

        assert "Supprimer" not in page
        assert fichier.status_code == 200


class TestDepot:
    def test_deposer_une_facture(self, client, alice, medias):
        reponse = client.post(reverse("documents:ajouter"), _donnees())

        document = Document.objects.get()
        assert reponse.url == reverse("documents:document", args=[document.pk])
        assert (document.foyer, document.cree_par) == (alice.foyer, alice.utilisateur)
        assert (document.montant, document.echeance) == (Decimal("84.20"), date(2026, 3, 20))
        assert (document.nom_fichier, document.type_mime) == ("facture.pdf", "application/pdf")
        assert document.taille == len(PDF_MINIMAL)
        assert document.est_a_payer
        assert (medias / document.fichier.name).read_bytes() == PDF_MINIMAL

    def test_un_fichier_deguise_est_refuse(self, client, alice, medias):
        piege = SimpleUploadedFile("facture.pdf", b"<script>alert(1)</script>", "application/pdf")

        reponse = client.post(reverse("documents:ajouter"), _donnees(fichier=piege))

        assert reponse.status_code == 200
        assert "Seuls les PDF" in reponse.content.decode()
        assert not Document.objects.exists()
        assert not any(medias.rglob("*.*"))

    def test_le_fichier_est_obligatoire_a_la_creation(self, client, alice):
        donnees = _donnees()
        del donnees["fichier"]

        assert client.post(reverse("documents:ajouter"), donnees).status_code == 200
        assert not Document.objects.exists()

    def test_seule_une_facture_porte_une_date_de_paiement(self, client, alice):
        client.post(
            reverse("documents:ajouter"),
            _donnees(type=TypeDocument.CONTRAT, paye_le="2026-03-02"),
        )

        assert Document.objects.get().paye_le is None


class TestModification:
    def test_modifier_sans_changer_de_fichier(self, client, alice, medias):
        document = FabriqueDocument(foyer=alice.foyer)
        chemin = document.fichier.name
        donnees = _donnees(titre="Renommé")
        del donnees["fichier"]

        client.post(reverse("documents:modifier", args=[document.pk]), donnees)

        document.refresh_from_db()
        assert (document.titre, document.fichier.name) == ("Renommé", chemin)
        assert (medias / chemin).exists()

    def test_remplacer_le_fichier_supprime_l_ancien(
        self, client, alice, medias, django_capture_on_commit_callbacks
    ):
        document = FabriqueDocument(foyer=alice.foyer)
        ancien = medias / document.fichier.name
        image = SimpleUploadedFile("scan.png", PNG_MINIMAL, "image/png")

        with django_capture_on_commit_callbacks(execute=True):
            client.post(reverse("documents:modifier", args=[document.pk]), _donnees(fichier=image))

        document.refresh_from_db()
        assert document.type_mime == "image/png" and document.fichier.name.endswith(".png")
        assert not ancien.exists()

    def test_supprimer_efface_aussi_le_fichier(
        self, client, alice, medias, django_capture_on_commit_callbacks
    ):
        document = FabriqueDocument(foyer=alice.foyer)
        chemin = medias / document.fichier.name

        with django_capture_on_commit_callbacks(execute=True):
            client.post(reverse("documents:supprimer", args=[document.pk]))

        assert not Document.objects.exists()
        assert not chemin.exists()

    def test_basculer_le_paiement(self, client, alice):
        facture = FabriqueDocument(foyer=alice.foyer)
        url = reverse("documents:paiement", args=[facture.pk])

        client.post(url)
        facture.refresh_from_db()
        assert facture.paye_le == date.today()

        client.post(url)
        facture.refresh_from_db()
        assert facture.paye_le is None

    def test_un_contrat_ne_se_paie_pas(self, client, alice):
        contrat = FabriqueDocument(foyer=alice.foyer, type=TypeDocument.CONTRAT)

        reponse = client.post(reverse("documents:paiement", args=[contrat.pk]))

        assert reponse.status_code == 404

    def test_le_retour_apres_paiement_ne_sort_pas_du_site(self, client, alice):
        facture = FabriqueDocument(foyer=alice.foyer)

        reponse = client.post(
            reverse("documents:paiement", args=[facture.pk]), {"retour": "https://pirate.example"}
        )

        assert reponse.url == reverse("documents:document", args=[facture.pk])


class TestFichier:
    def test_en_tetes_de_securite(self, client, alice):
        document = FabriqueDocument(foyer=alice.foyer, nom_fichier="Facture mars.pdf")

        reponse = client.get(reverse("documents:fichier", args=[document.pk]))

        assert reponse["Content-Type"] == "application/pdf"
        assert reponse["X-Content-Type-Options"] == "nosniff"
        assert reponse["Content-Security-Policy"].startswith("sandbox")
        assert "private" in reponse["Cache-Control"]
        assert reponse["Content-Disposition"].startswith("inline")
        assert b"".join(reponse.streaming_content) == PDF_MINIMAL

    def test_telecharger(self, client, alice):
        document = FabriqueDocument(foyer=alice.foyer)

        reponse = client.get(reverse("documents:fichier", args=[document.pk]) + "?telecharger")

        assert reponse["Content-Disposition"].startswith("attachment")


class TestListe:
    def test_filtrer_les_factures_a_payer(self, client, alice):
        FabriqueDocument(foyer=alice.foyer, titre="À régler")
        FabriqueDocument(foyer=alice.foyer, titre="Réglée", paye_le=date(2026, 3, 5))
        FabriqueDocument(foyer=alice.foyer, titre="Bail", type=TypeDocument.CONTRAT)

        reponse = client.get(reverse("documents:liste"), {"a_payer": "on"})

        assert [d.titre for d in reponse.context["documents"]] == ["À régler"]

    def test_rechercher_sur_l_emetteur(self, client, alice):
        FabriqueDocument(foyer=alice.foyer, titre="Facture", emetteur="Électricien Dupont")
        FabriqueDocument(foyer=alice.foyer, titre="Autre", emetteur="Plombier")

        reponse = client.get(reverse("documents:liste"), {"recherche": "dupont"})

        assert [d.titre for d in reponse.context["documents"]] == ["Facture"]
