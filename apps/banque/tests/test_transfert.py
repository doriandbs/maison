from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

import pytest
from django.urls import reverse

from apps.banque.models import Categorie, Compte, Nature, Operation, RegleCategorisation
from apps.banque.services import regles, transfert
from apps.banque.services.operations import creer_virement
from apps.documents.tests.fabriques import FabriqueDocument
from apps.foyers.middleware import CLE_SESSION_FOYER
from apps.foyers.models import Role
from apps.foyers.tests.fabriques import FabriqueAdhesion, FabriqueFoyer
from apps.prets.models import Pret, RemboursementAnticipe
from apps.prets.tests.fabriques import FabriquePret, FabriqueRemboursement

from .fabriques import FabriqueCompte, FabriqueOperation, FabriqueReleveSolde

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def medias(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


def _categorie(foyer, parente, nom, nature=Nature.DEPENSE):
    parent, _ = Categorie.objects.get_or_create(
        foyer=foyer, nom=parente, parent=None, defaults={"nature": nature}
    )
    return Categorie.objects.create(foyer=foyer, nom=nom, parent=parent, nature=nature)


@pytest.fixture
def monde():
    """Dorian : son foyer perso (A, propriétaire) et le foyer commun (B, membre)."""
    perso = FabriqueAdhesion(role=Role.PROPRIETAIRE, foyer__nom="Perso", est_principal=True)
    dorian = perso.utilisateur
    commun = FabriqueAdhesion(utilisateur=dorian, role=Role.MEMBRE, foyer__nom="Commun")
    courses_a = _categorie(perso.foyer, "Alimentation", "Courses")
    courses_b = _categorie(commun.foyer, "ALIMENTATION", "courses")  # même nom, autre casse
    sport_a = _categorie(perso.foyer, "Loisirs", "Sport")
    compte = FabriqueCompte(foyer=perso.foyer, nom="Courant SG", ouvert_le=date(2026, 1, 1))
    compte.titulaires.set([perso, FabriqueAdhesion(foyer=perso.foyer)])
    return SimpleNamespace(
        perso=perso,
        commun=commun,
        a=perso.foyer,
        b=commun.foyer,
        compte=compte,
        courses_a=courses_a,
        courses_b=courses_b,
        sport_a=sport_a,
    )


class TestService:
    def test_tout_suit_le_compte(self, monde):
        courses = FabriqueOperation(compte=monde.compte, categorie=monde.courses_a)
        sport = FabriqueOperation(compte=monde.compte, categorie=monde.sport_a)
        releve = FabriqueReleveSolde(compte=monde.compte)
        doc_compte = FabriqueDocument(foyer=monde.a, compte=monde.compte, categorie=monde.sport_a)
        doc_operation = FabriqueDocument(foyer=monde.a, operation=courses)
        pret = FabriquePret(foyer=monde.a, compte=monde.compte)
        remboursement = FabriqueRemboursement(pret=pret)
        reste = FabriqueDocument(foyer=monde.a, titre="Reste ici")

        bilan = transfert.transferer([monde.compte], monde.a, monde.b)

        for objet in (
            monde.compte,
            courses,
            sport,
            releve,
            doc_compte,
            doc_operation,
            pret,
            remboursement,
            reste,
        ):
            objet.refresh_from_db()
            assert objet.foyer == (monde.a if objet is reste else monde.b)
        assert courses.categorie == monde.courses_b  # reprise par le nom
        assert sport.categorie.foyer == monde.b and str(sport.categorie) == "Loisirs › Sport"
        assert doc_compte.categorie == sport.categorie
        assert list(monde.compte.titulaires.all()) == [monde.commun]
        assert (bilan.operations, bilan.releves, bilan.documents, bilan.prets) == (2, 1, 2, 1)
        assert bilan.categories_creees == ["Loisirs › Sport"]

    def test_l_apercu_ne_modifie_rien(self, monde):
        FabriqueOperation(compte=monde.compte, categorie=monde.sport_a)

        bilan = transfert.preparer([monde.compte], monde.a, monde.b)

        monde.compte.refresh_from_db()
        assert monde.compte.foyer == monde.a
        assert bilan.operations == 1 and bilan.categories_creees == ["Loisirs › Sport"]
        assert not Categorie.objects.filter(foyer=monde.b, nom="Sport").exists()

    def test_virement_rompu_si_l_autre_compte_reste(self, monde):
        livret = FabriqueCompte(foyer=monde.a, ouvert_le=date(2026, 1, 1))
        debit, credit = creer_virement(
            source=monde.compte,
            destination=livret,
            date_virement=date(2026, 3, 1),
            montant=D("100"),
            libelle="Épargne",
        )

        assert transfert.preparer([monde.compte], monde.a, monde.b).virements_rompus == 1
        transfert.transferer([monde.compte], monde.a, monde.b)

        debit.refresh_from_db()
        credit.refresh_from_db()
        assert debit.groupe_virement is None and credit.groupe_virement is None
        assert (debit.foyer, credit.foyer) == (monde.b, monde.a)

    def test_virement_conserve_si_les_deux_comptes_partent(self, monde):
        livret = FabriqueCompte(foyer=monde.a, ouvert_le=date(2026, 1, 1))
        debit, _ = creer_virement(
            source=monde.compte,
            destination=livret,
            date_virement=date(2026, 3, 1),
            montant=D("100"),
            libelle="Épargne",
        )

        bilan = transfert.transferer([monde.compte, livret], monde.a, monde.b)

        debit.refresh_from_db()
        assert bilan.virements_rompus == 0 and debit.groupe_virement is not None

    def test_nom_deja_pris_a_l_arrivee(self, monde):
        FabriqueCompte(foyer=monde.b, nom="Courant SG")
        FabriqueCompte(foyer=monde.b, nom="Courant SG (Perso)")

        bilan = transfert.transferer([monde.compte], monde.a, monde.b)

        monde.compte.refresh_from_db()
        assert monde.compte.nom == "Courant SG (Perso 2)"
        assert bilan.renommes == [("Courant SG", "Courant SG (Perso 2)")]

    def test_document_lie_a_ce_qui_reste_est_detache(self, monde):
        reste = FabriqueCompte(foyer=monde.a)
        operation_restante = FabriqueOperation(compte=reste)
        document = FabriqueDocument(
            foyer=monde.a, compte=monde.compte, operation=operation_restante
        )

        transfert.transferer([monde.compte], monde.a, monde.b)

        document.refresh_from_db()
        assert document.foyer == monde.b and document.operation is None

    @pytest.mark.parametrize("copier", [True, False])
    def test_regles(self, monde, copier):
        regles.memoriser(monde.a, "LIDL", monde.courses_a)
        regles.memoriser(monde.a, "Decathlon", monde.sport_a)
        regles.memoriser(monde.b, "lidl", monde.courses_b)

        bilan = transfert.transferer([monde.compte], monde.a, monde.b, copier_regles=copier)

        motifs = set(
            RegleCategorisation.objects.filter(foyer=monde.b).values_list("motif", flat=True)
        )
        assert motifs == ({"lidl", "Decathlon"} if copier else {"lidl"})
        assert bilan.regles == (1 if copier else 0)

    @pytest.mark.parametrize("cas", ["meme_foyer", "compte_d_ailleurs", "aucun"])
    def test_refus(self, monde, cas):
        comptes, destination = [monde.compte], monde.b
        if cas == "meme_foyer":
            destination = monde.a
        elif cas == "compte_d_ailleurs":
            comptes = [FabriqueCompte()]
        else:
            comptes = []

        with pytest.raises(transfert.ErreurTransfert):
            transfert.transferer(comptes, monde.a, destination)


class TestEcran:
    def _client(self, client, monde):
        client.force_login(monde.perso.utilisateur)
        return client

    def test_apercu_puis_confirmation(self, client, monde):
        client = self._client(client, monde)
        url = reverse("banque:transferer_comptes")
        donnees = {"destination": monde.b.pk, "comptes": [monde.compte.pk], "copier_regles": "on"}

        apercu = client.post(url, donnees)
        monde.compte.refresh_from_db()
        assert apercu.context["bilan"].comptes == [monde.compte]
        assert monde.compte.foyer == monde.a

        reponse = client.post(url, donnees | {"confirmer": "1"})
        monde.compte.refresh_from_db()
        assert reponse.url == reverse("banque:comptes")
        assert monde.compte.foyer == monde.b
        assert client.session[CLE_SESSION_FOYER] == monde.b.pk

    def test_seuls_les_foyers_ou_l_on_peut_ecrire_sont_proposes(self, client, monde):
        lecture_seule = FabriqueAdhesion(utilisateur=monde.perso.utilisateur, role=Role.LECTEUR)
        etranger = FabriqueFoyer()

        formulaire = (
            self._client(client, monde).get(reverse("banque:transferer_comptes")).context["form"]
        )

        proposes = set(formulaire.fields["destination"].queryset)
        assert proposes == {monde.b}
        assert lecture_seule.foyer not in proposes and etranger not in proposes

    @pytest.mark.parametrize("vers", ["etranger", "lecture_seule"])
    def test_impossible_d_envoyer_vers_un_foyer_interdit(self, client, monde, vers):
        if vers == "etranger":
            cible = FabriqueFoyer()
        else:
            cible = FabriqueAdhesion(utilisateur=monde.perso.utilisateur, role=Role.LECTEUR).foyer

        self._client(client, monde).post(
            reverse("banque:transferer_comptes"),
            {"destination": cible.pk, "comptes": [monde.compte.pk], "confirmer": "1"},
        )

        monde.compte.refresh_from_db()
        assert monde.compte.foyer == monde.a

    def test_impossible_de_prendre_le_compte_d_un_autre_foyer(self, client, monde):
        autre = FabriqueCompte(nom="Compte d'autrui")

        self._client(client, monde).post(
            reverse("banque:transferer_comptes"),
            {"destination": monde.b.pk, "comptes": [autre.pk], "confirmer": "1"},
        )

        autre.refresh_from_db()
        assert autre.foyer != monde.b

    def test_un_simple_membre_ne_peut_pas_vider_le_foyer(self, client, monde):
        compte_b = FabriqueCompte(foyer=monde.b)
        client.force_login(monde.perso.utilisateur)
        session = client.session
        session[CLE_SESSION_FOYER] = monde.b.pk  # Dorian n'est que membre du foyer commun
        session.save()

        reponse = client.post(
            reverse("banque:transferer_comptes"),
            {"destination": monde.a.pk, "comptes": [compte_b.pk], "confirmer": "1"},
        )

        assert reponse.status_code == 403
        assert Compte.objects.get(pk=compte_b.pk).foyer == monde.b

    def test_bouton_visible_seulement_avec_plusieurs_foyers(self, client, monde):
        page = self._client(client, monde).get(reverse("banque:comptes")).content.decode()
        assert "Déplacer vers un autre foyer" in page

        seul = FabriqueAdhesion(role=Role.PROPRIETAIRE, est_principal=True)
        FabriqueCompte(foyer=seul.foyer)
        client.force_login(seul.utilisateur)
        assert "Déplacer vers" not in client.get(reverse("banque:comptes")).content.decode()


def test_apres_le_deplacement_l_ancien_foyer_ne_voit_plus_rien(client, monde):
    autre_membre = FabriqueAdhesion(foyer=monde.a, role=Role.MEMBRE, est_principal=True)
    operation = FabriqueOperation(compte=monde.compte, libelle="Opération déplacée")
    transfert.transferer([monde.compte], monde.a, monde.b)
    client.force_login(autre_membre.utilisateur)

    assert client.get(reverse("banque:compte", args=[monde.compte.pk])).status_code == 404
    assert "déplacée" not in client.get(reverse("banque:operations")).content.decode()
    assert Operation.objects.get(pk=operation.pk).foyer == monde.b
    assert Pret.objects.count() == RemboursementAnticipe.objects.count() == 0
