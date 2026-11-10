# ruff: noqa: E501  (lignes de relevé reproduites telles que la banque les exporte)
from datetime import date
from decimal import Decimal as D

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.urls import reverse

from apps.banque.importation import (
    TAILLE_MAX,
    ErreurImport,
    depuis_session,
    lire_releve,
    vers_session,
)
from apps.banque.importation.societe_generale import libelle_lisible
from apps.banque.models import Operation, RegleCategorisation, TypeCompte
from apps.banque.services import importation, regles
from apps.banque.services.importation import Statut
from apps.banque.services.soldes import soldes_des_comptes
from apps.foyers.models import Role
from apps.foyers.tests.fabriques import FabriqueAdhesion

from .fabriques import FabriqueCompte, FabriqueOperation, FabriqueSousCategorie

ENTETE = "Date de l'opération;Libellé;Détail de l'écriture;Montant de l'opération;Devise"


def csv_sg(*lignes: str, solde: str = "1000.00", encodage: str = "cp1252") -> bytes:
    """Relevé fictif au format de la Société Générale."""
    texte = "\r\n".join(
        [f"00012345678;01/11/2026;10/11/2026;{len(lignes)};10/11/2026;{solde} EUR", "", ENTETE]
        + list(lignes)
    )
    return texte.encode(encodage)


CARTE = "06/11/2026;CARTE X1234 05/11 ;CARTE X1234 05/11 SNCF-VOYAGEURS COMMERCE ELECTRONIQUE 230631004122822ILID;-78,00;EUR"
PRELEVEMENT = "05/11/2026;PRELEVEMENT EUROPE;PRELEVEMENT EUROPEEN 2905863925 DE: AXA ID: FR14ZZZ391832 MOTIF: CONTRAT 12;-56,80;EUR"
SALAIRE = "04/11/2026;VIR RECU    348805;VIR RECU    3488055052S DE: ACME SA MOTIF: SALAIRE NOVEMBRE;2500,00;EUR"


# --- Lecture du fichier -------------------------------------------------------


class TestLectureSocieteGenerale:
    def test_lit_les_lignes_et_le_solde_annonce(self):
        releve = lire_releve(csv_sg(CARTE, PRELEVEMENT, SALAIRE, solde="33823.67"))

        assert releve.banque.startswith("Société Générale")
        assert (releve.solde, releve.date_solde) == (D("33823.67"), date(2026, 11, 10))
        assert [(ligne.date, ligne.montant) for ligne in releve.lignes] == [
            (date(2026, 11, 6), D("-78.00")),
            (date(2026, 11, 5), D("-56.80")),
            (date(2026, 11, 4), D("2500.00")),
        ]
        assert releve.lignes[0].libelle_banque.startswith("CARTE X1234 05/11 SNCF")

    @pytest.mark.parametrize("encodage", ["cp1252", "utf-8", "utf-8-sig"])
    def test_accepte_latin1_et_utf8(self, encodage):
        ligne = "07/11/2026;ECHEANCE PRET N°82;ECHEANCE PRET N°826 ASSURANCE : 4,68;-44,68;EUR"

        releve = lire_releve(csv_sg(ligne, encodage=encodage))

        assert "N°826" in releve.lignes[0].libelle_banque

    def test_sans_premiere_ligne_le_solde_est_inconnu(self):
        releve = lire_releve(f"{ENTETE}\r\n{CARTE}".encode("cp1252"))

        assert releve.solde is None and len(releve.lignes) == 1

    @pytest.mark.parametrize(
        "premiere", ["Relevé de compte", "1;01/11/2026;10/11/2026;1;99/99/2026;12.00 EUR"]
    )
    def test_premiere_ligne_inattendue_le_solde_est_inconnu(self, premiere):
        releve = lire_releve(f"{premiere}\r\n\r\n{ENTETE}\r\n{CARTE}".encode("cp1252"))

        assert releve.solde is None and len(releve.lignes) == 1

    def test_ignore_les_lignes_vides(self):
        assert len(lire_releve(csv_sg(CARTE, "", ";;;", SALAIRE)).lignes) == 2

    def test_montant_avec_separateur_de_milliers(self):
        releve = lire_releve(csv_sg("04/11/2026;VIR;VIR RECU 1 DE: X MOTIF: Y;1 234,56;EUR"))

        assert releve.lignes[0].montant == D("1234.56")

    @pytest.mark.parametrize(
        ("contenu", "message"),
        [
            (b"date;montant\n01/01/2026;12", "non reconnu"),
            (csv_sg(), "aucune opération"),
            (csv_sg("32/11/2026;X;X;-1,00;EUR"), "Date illisible"),
            (csv_sg("01/11/2026;X;X;douze;EUR"), "Montant illisible"),
            (csv_sg("01/11/2026;X;X"), "incomplète"),
            (csv_sg("01/11/2026;X;X;-1,00;USD"), "euros"),
        ],
    )
    def test_fichiers_refuses(self, contenu, message):
        with pytest.raises(ErreurImport, match=message):
            lire_releve(contenu)

    def test_taille_maximale(self):
        with pytest.raises(ErreurImport, match="2 Mo"):
            lire_releve(b"x" * (TAILLE_MAX + 1))

    def test_nombre_de_lignes_maximal(self, monkeypatch):
        monkeypatch.setattr("apps.banque.importation.LIGNES_MAX", 1)

        with pytest.raises(ErreurImport, match="dépasse 1"):
            lire_releve(csv_sg(CARTE, SALAIRE))

    def test_aller_retour_en_session(self):
        releve = lire_releve(csv_sg(CARTE, SALAIRE, solde="12.34"))

        assert depuis_session(vers_session(releve)) == releve

    def test_aller_retour_sans_solde(self):
        releve = lire_releve(f"{ENTETE}\r\n{CARTE}".encode())

        assert depuis_session(vers_session(releve)) == releve


@pytest.mark.parametrize(
    ("detail", "libelle", "tiers"),
    [
        (
            "CARTE X2706 04/11 CARREFOUR CITY 110630802090210IOPD",
            "CARREFOUR CITY",
            "CARREFOUR CITY",
        ),
        (
            "CARTE X2706 05/11 SNCF-VOYAGEURS COMMERCE ELECTRONIQUE 230631004122822ILID",
            "SNCF-VOYAGEURS",
            "SNCF-VOYAGEURS",
        ),
        ("CARTE X2706 01/11 UBER *EATS 23,81 EUR PAYS-BAS", "UBER *EATS", "UBER *EATS"),
        ("CARTE X2706 03/11 RETRAIT DAB 03/11 POISSY", "03/11 POISSY", "03/11 POISSY"),
        (
            "PRELEVEMENT EUROPEEN 2905863925 DE: AXA ID: FR14ZZZ391832 MOTIF: X",
            "Prélèvement – AXA",
            "AXA",
        ),
        (
            "PRLV EUROPEEN ACC 1234567890 DE: SOGECAP ID: FR12ZZZ123456 MOTIF: X",
            "Prélèvement – SOGECAP",
            "SOGECAP",
        ),
        (
            "PRELEVEMENT EUROPEEN 2005515982 POUR CPTE DE:DGFIP IMPOT 078 ID: FR46ZZZ005002 MOTIF: X",
            "Prélèvement – DGFIP IMPOT",
            "DGFIP IMPOT",
        ),
        (
            "VIR RECU 3684704452S DE: EDF CLT PART RBT SCT MOTIF: REMBOURSEMENT",
            "Virement reçu – EDF CLT PART RBT SCT",
            "EDF CLT PART RBT SCT",
        ),
        (
            "VIR INST RE 680289123456 DE: MME DUPONT DATE: 01/11/2026 10:00 MOTIF: Loyer",
            "Virement reçu – MME DUPONT",
            "MME DUPONT",
        ),
        (
            "000001 VIR EUROPEEN EMIS LOGITEL POUR: M DUPONT 05 11 SG 12345 CPT 1 REF: 2",
            "Virement émis – M DUPONT",
            "M DUPONT",
        ),
        (
            "000001 VIR INSTANTANE EMIS LOGITEL POUR: SYNDIC GESTION 05 11 BQ X CPT 1",
            "Virement émis – SYNDIC GESTION",
            "SYNDIC GESTION",
        ),
        (
            "ECHEANCE PRET N°826051372808 ASSURANCE : 44,68",
            "Échéance de prêt",
            "ECHEANCE PRET",
        ),
        (
            "FRAIS PAIEMENT HORS ZONE EURO CARTE X2706 01/11 34,42 EUR",
            "Frais de paiement hors zone euro",
            "FRAIS PAIEMENT HORS ZONE EURO",
        ),
        (
            "VIREMENT EMIS PAR SOCIETE GENERALE POUR TRANSFERT DU SOLDE DE VOTRE COMPTE 1 2",
            "Transfert du solde (changement d'agence)",
            "TRANSFERT DU SOLDE",
        ),
        ("COTISATION JAZZ 123456789012", "COTISATION JAZZ", "COTISATION JAZZ"),
        ("OPTION TRANQUILLITE  JEUNE", "OPTION TRANQUILLITE JEUNE", "OPTION TRANQUILLITE JEUNE"),
    ],
)
def test_libelle_lisible(detail, libelle, tiers):
    assert libelle_lisible(detail) == (libelle, tiers)


# --- Préparation et enregistrement -------------------------------------------

pytestmark = pytest.mark.django_db


@pytest.fixture
def compte():
    return FabriqueCompte(solde_initial=D("100.00"), ouvert_le=date(2026, 10, 31))


def _importer_tout(compte, contenu: bytes) -> int:
    apercu = importation.preparer(compte, lire_releve(contenu))
    choix = [importation.Choix(ligne, ligne.categorie) for ligne in apercu.lignes]
    return importation.enregistrer(compte, choix, cree_par=None)


class TestPreparation:
    def test_toutes_nouvelles(self, compte):
        apercu = importation.preparer(compte, lire_releve(csv_sg(CARTE, SALAIRE)))

        assert [ligne.statut for ligne in apercu.lignes] == [Statut.NOUVELLE, Statut.NOUVELLE]
        assert all(ligne.cochee_par_defaut for ligne in apercu.lignes)

    def test_reimporter_le_meme_releve_ne_cree_rien(self, compte):
        assert _importer_tout(compte, csv_sg(CARTE, SALAIRE)) == 2

        apercu = importation.preparer(compte, lire_releve(csv_sg(SALAIRE, CARTE)))

        assert {ligne.statut for ligne in apercu.lignes} == {Statut.DEJA_IMPORTEE}
        assert _importer_tout(compte, csv_sg(CARTE, SALAIRE)) == 0
        assert Operation.objects.filter(compte=compte).count() == 2

    def test_deux_lignes_identiques_le_meme_jour_sont_deux_operations(self, compte):
        assert _importer_tout(compte, csv_sg(CARTE, CARTE)) == 2

        assert _importer_tout(compte, csv_sg(CARTE, CARTE, CARTE)) == 1

    def test_doublon_possible_avec_une_saisie_manuelle(self, compte):
        FabriqueOperation(compte=compte, date=date(2026, 11, 6), montant=D("-78.00"))

        apercu = importation.preparer(compte, lire_releve(csv_sg(CARTE)))

        assert apercu.lignes[0].statut == Statut.DOUBLON_POSSIBLE
        assert apercu.lignes[0].importable and not apercu.lignes[0].cochee_par_defaut

    def test_lignes_anterieures_au_solde_initial(self, compte):
        compte.ouvert_le = date(2026, 11, 5)
        compte.save()

        apercu = importation.preparer(compte, lire_releve(csv_sg(CARTE, PRELEVEMENT, SALAIRE)))

        assert [ligne.statut for ligne in apercu.lignes] == [
            Statut.NOUVELLE,
            Statut.ANTERIEURE,
            Statut.ANTERIEURE,
        ]
        assert apercu.nouveau_debut == date(2026, 11, 3)

    def test_categorie_proposee_par_les_regles(self, compte):
        transport = FabriqueSousCategorie(parent__foyer=compte.foyer, nom="Train")
        regles.memoriser(compte.foyer, "sncf", transport)

        apercu = importation.preparer(compte, lire_releve(csv_sg(CARTE, SALAIRE)))

        assert [ligne.categorie for ligne in apercu.lignes] == [transport, None]

    def test_controle_du_solde_avec_la_banque(self, compte):
        # 100 de solde initial - 78 - 56,80 + 2500 = 2465,20
        apercu = importation.preparer(
            compte, lire_releve(csv_sg(CARTE, PRELEVEMENT, SALAIRE, solde="2465.20"))
        )
        assert (apercu.solde_calcule, apercu.ecart) == (D("2465.20"), D("0.00"))

        manque = importation.preparer(compte, lire_releve(csv_sg(CARTE, SALAIRE, solde="2465.20")))
        assert manque.ecart == D("-56.80")

    def test_pas_de_controle_pour_un_placement(self):
        pea = FabriqueCompte(type=TypeCompte.PEA, ouvert_le=date(2026, 1, 1))

        apercu = importation.preparer(pea, lire_releve(csv_sg(CARTE)))

        assert apercu.solde_calcule is None and apercu.ecart is None
        assert apercu.nouveau_debut is None

    def test_sans_solde_annonce_pas_de_controle(self, compte):
        apercu = importation.preparer(compte, lire_releve(f"{ENTETE}\r\n{CARTE}".encode()))

        assert apercu.ecart is None


class TestAvancerLeDebut:
    def test_l_historique_s_ajoute_sans_changer_le_solde_actuel(self, compte):
        compte.ouvert_le = date(2026, 11, 10)
        compte.solde_initial = D("2465.20")  # solde du jour, saisi à la création du compte
        compte.save()
        contenu = csv_sg(CARTE, PRELEVEMENT, SALAIRE)

        importation.avancer_le_debut(importation.preparer(compte, lire_releve(contenu)))
        compte.refresh_from_db()
        importees = _importer_tout(compte, contenu)

        assert compte.ouvert_le == date(2026, 11, 3)
        assert compte.solde_initial == D("100.00")
        assert importees == 3
        assert soldes_des_comptes(compte.foyer)[compte.pk] == D("2465.20")

    def test_sans_ligne_anterieure_rien_ne_change(self, compte):
        importation.avancer_le_debut(importation.preparer(compte, lire_releve(csv_sg(CARTE))))

        compte.refresh_from_db()
        assert (compte.ouvert_le, compte.solde_initial) == (date(2026, 10, 31), D("100.00"))


class TestEnregistrement:
    def test_n_enregistre_que_les_lignes_importables(self, compte):
        compte.ouvert_le = date(2026, 11, 5)
        compte.save()
        apercu = importation.preparer(compte, lire_releve(csv_sg(CARTE, PRELEVEMENT)))

        nombre = importation.enregistrer(
            compte, [importation.Choix(ligne, None) for ligne in apercu.lignes], cree_par=None
        )

        operation = Operation.objects.get(compte=compte)
        assert nombre == 1
        assert (operation.libelle, operation.montant) == ("SNCF-VOYAGEURS", D("-78.00"))
        assert operation.libelle_banque.startswith("CARTE X1234")
        assert operation.foyer == compte.foyer

    def test_ignore_une_ligne_a_zero(self, compte):
        assert _importer_tout(compte, csv_sg("06/11/2026;X;CARTE X1 05/11 GRATUIT;0,00;EUR")) == 0

    def test_la_base_refuse_deux_fois_la_meme_empreinte(self, compte):
        FabriqueOperation(compte=compte, empreinte_import="abc")

        with pytest.raises(IntegrityError):
            FabriqueOperation(compte=compte, empreinte_import="abc")


# --- Règles ---------------------------------------------------------------------


class TestRegles:
    def test_normaliser(self):
        assert regles.normaliser("  Échéance   PRÊT ") == "echeance pret"

    def test_le_motif_le_plus_long_l_emporte(self, compte):
        foyer = compte.foyer
        transport = FabriqueSousCategorie(parent__foyer=foyer, nom="Taxi")
        repas = FabriqueSousCategorie(parent__foyer=foyer, nom="Livraison")
        regles.memoriser(foyer, "UBER", transport)
        regles.memoriser(foyer, "uber *eats", repas)

        classeur = regles.Classeur(foyer)

        assert classeur.categorie("UBER *EATS") == repas
        assert classeur.categorie("UBER TRIP") == transport
        assert classeur.categorie("Carrefour") is None

    def test_ignore_casse_et_accents(self, compte):
        sante = FabriqueSousCategorie(parent__foyer=compte.foyer)
        regles.memoriser(compte.foyer, "pharmacie de l'église", sante)

        assert regles.Classeur(compte.foyer).categorie("PHARMACIE DE L'EGLISE") == sante

    def test_une_categorie_archivee_n_est_plus_proposee(self, compte):
        archivee = FabriqueSousCategorie(parent__foyer=compte.foyer, archive_le="2026-01-01T00:00Z")
        regles.memoriser(compte.foyer, "AXA", archivee)

        assert regles.Classeur(compte.foyer).categorie("Prélèvement – AXA") is None

    def test_les_regles_d_un_autre_foyer_ne_s_appliquent_pas(self, compte):
        ailleurs = FabriqueSousCategorie()
        regles.memoriser(ailleurs.foyer, "SNCF", ailleurs)

        assert regles.Classeur(compte.foyer).categorie("SNCF") is None

    def test_memoriser_met_a_jour_une_regle_existante(self, compte):
        a = FabriqueSousCategorie(parent__foyer=compte.foyer)
        b = FabriqueSousCategorie(parent__foyer=compte.foyer)
        premiere = regles.memoriser(compte.foyer, "Free  Mobile", a)

        seconde = regles.memoriser(compte.foyer, "FREE MOBILE", b)

        assert seconde.pk == premiere.pk and seconde.categorie == b
        assert premiere.motif == "Free Mobile"
        assert RegleCategorisation.objects.count() == 1

    def test_appliquer_aux_operations_a_classer(self, compte):
        courses = FabriqueSousCategorie(parent__foyer=compte.foyer)
        autre = FabriqueSousCategorie(parent__foyer=compte.foyer)
        regles.memoriser(compte.foyer, "carrefour", courses)
        a_classer = FabriqueOperation(compte=compte, libelle="CARREFOUR CITY")
        deja = FabriqueOperation(compte=compte, libelle="CARREFOUR MARKET", categorie=autre)
        inconnue = FabriqueOperation(compte=compte, libelle="BOULANGERIE")
        par_le_detail = FabriqueOperation(
            compte=compte, libelle="Achat", libelle_banque="CARTE X1 CARREFOUR 123"
        )

        assert regles.appliquer_aux_operations_a_classer(compte.foyer) == 2

        for operation in (a_classer, deja, inconnue, par_le_detail):
            operation.refresh_from_db()
        assert (a_classer.categorie, deja.categorie, inconnue.categorie) == (courses, autre, None)
        assert par_le_detail.categorie == courses

    def test_un_virement_interne_reste_sans_categorie(self, compte):
        from apps.banque.services.operations import creer_virement

        livret = FabriqueCompte(foyer=compte.foyer)
        regles.memoriser(
            compte.foyer, "virement", FabriqueSousCategorie(parent__foyer=compte.foyer)
        )
        creer_virement(
            source=compte,
            destination=livret,
            date_virement=date(2026, 11, 2),
            montant=D("10"),
            libelle="Virement interne",
        )

        assert regles.appliquer_aux_operations_a_classer(compte.foyer) == 0


# --- Écrans -------------------------------------------------------------------


@pytest.fixture
def alice(client):
    adhesion = FabriqueAdhesion(role=Role.MEMBRE, est_principal=True)
    client.force_login(adhesion.utilisateur)
    return adhesion


def _deposer(client, compte, contenu: bytes):
    return client.post(
        reverse("banque:importer"),
        {"compte": compte.pk, "fichier": SimpleUploadedFile("releve.csv", contenu, "text/csv")},
    )


class TestEcransImport:
    def test_parcours_complet(self, client, alice):
        compte = FabriqueCompte(foyer=alice.foyer, ouvert_le=date(2026, 10, 31))
        train = FabriqueSousCategorie(parent__foyer=alice.foyer, nom="Train")

        assert _deposer(client, compte, csv_sg(CARTE, SALAIRE)).url == reverse(
            "banque:apercu_import"
        )
        apercu = client.get(reverse("banque:apercu_import"))
        assert "SNCF-VOYAGEURS" in apercu.content.decode()

        reponse = client.post(
            reverse("banque:apercu_import"),
            {
                "action": "importer",
                "inclure_0": "on",
                "categorie_0": train.pk,
                "memoriser_0": "on",
                "inclure_1": "",
            },
        )

        assert reponse.url == f"{reverse('banque:operations')}?compte={compte.pk}"
        operation = Operation.objects.get(compte=compte)
        assert (operation.libelle, operation.categorie, operation.cree_par) == (
            "SNCF-VOYAGEURS",
            train,
            alice.utilisateur,
        )
        assert RegleCategorisation.objects.get(foyer=alice.foyer).motif == "SNCF-VOYAGEURS"
        assert client.get(reverse("banque:apercu_import")).url == reverse("banque:importer")

    def test_fichier_illisible(self, client, alice):
        compte = FabriqueCompte(foyer=alice.foyer)

        reponse = _deposer(client, compte, b"n'importe quoi")

        assert reponse.status_code == 200
        assert "non reconnu" in reponse.content.decode()

    def test_avancer_le_debut_depuis_l_apercu(self, client, alice):
        compte = FabriqueCompte(foyer=alice.foyer, ouvert_le=date(2026, 11, 10))
        _deposer(client, compte, csv_sg(CARTE))

        assert "Démarrer le compte" in client.get(reverse("banque:apercu_import")).content.decode()
        client.post(reverse("banque:apercu_import"), {"action": "avancer_debut"})

        compte.refresh_from_db()
        assert compte.ouvert_le == date(2026, 11, 5)

    def test_annuler(self, client, alice):
        _deposer(client, FabriqueCompte(foyer=alice.foyer), csv_sg(CARTE))

        client.post(reverse("banque:apercu_import"), {"action": "annuler"})

        assert client.get(reverse("banque:apercu_import")).url == reverse("banque:importer")
        assert not Operation.objects.exists()


class TestIsolationImport:
    def test_impossible_d_importer_dans_le_compte_d_autrui(self, client, alice):
        compte_b = FabriqueCompte(nom="Compte secret")

        reponse = _deposer(client, compte_b, csv_sg(CARTE))

        assert reponse.status_code == 200
        assert "import_releve" not in client.session

    def test_categorie_d_autrui_refusee(self, client, alice):
        compte = FabriqueCompte(foyer=alice.foyer, ouvert_le=date(2026, 10, 31))
        categorie_b = FabriqueSousCategorie()
        _deposer(client, compte, csv_sg(CARTE))

        client.post(
            reverse("banque:apercu_import"),
            {"action": "importer", "inclure_0": "on", "categorie_0": categorie_b.pk},
        )

        assert not Operation.objects.exists()

    def test_l_apercu_ne_suit_pas_un_changement_de_foyer(self, client, alice):
        _deposer(client, FabriqueCompte(foyer=alice.foyer), csv_sg(CARTE))
        session = client.session
        session["import_releve"]["foyer"] = alice.foyer.pk + 1000
        session.save()

        assert client.get(reverse("banque:apercu_import")).url == reverse("banque:importer")

    def test_un_lecteur_ne_peut_pas_importer(self, client):
        lecteur = FabriqueAdhesion(role=Role.LECTEUR)
        compte = FabriqueCompte(foyer=lecteur.foyer)
        client.force_login(lecteur.utilisateur)

        assert _deposer(client, compte, csv_sg(CARTE)).status_code == 403
        assert client.post(reverse("banque:apercu_import"), {}).status_code == 403
        assert client.post(reverse("banque:appliquer_regles")).status_code == 403

    def test_supprimer_la_regle_d_autrui_est_introuvable(self, client, alice):
        ailleurs = FabriqueSousCategorie()
        regle = regles.memoriser(ailleurs.foyer, "SNCF", ailleurs)

        assert client.post(reverse("banque:supprimer_regle", args=[regle.pk])).status_code == 404
        assert RegleCategorisation.objects.filter(pk=regle.pk).exists()


class TestEcransRegles:
    def test_ajouter_appliquer_supprimer(self, client, alice):
        courses = FabriqueSousCategorie(parent__foyer=alice.foyer, nom="Courses")
        operation = FabriqueOperation(compte=FabriqueCompte(foyer=alice.foyer), libelle="LIDL")

        client.post(reverse("banque:regles"), {"motif": " lidl ", "categorie": courses.pk})
        client.post(reverse("banque:appliquer_regles"))
        regle = RegleCategorisation.objects.get()
        client.post(reverse("banque:supprimer_regle", args=[regle.pk]))

        operation.refresh_from_db()
        assert regle.motif == "lidl" and operation.categorie == courses
        assert not RegleCategorisation.objects.exists()

    def test_motif_en_double_refuse(self, client, alice):
        courses = FabriqueSousCategorie(parent__foyer=alice.foyer)
        regles.memoriser(alice.foyer, "LIDL", courses)

        reponse = client.post(reverse("banque:regles"), {"motif": "lidl", "categorie": courses.pk})

        assert "existe déjà" in reponse.content.decode()

    def test_categorie_d_autrui_refusee(self, client, alice):
        client.post(
            reverse("banque:regles"), {"motif": "X", "categorie": FabriqueSousCategorie().pk}
        )

        assert not RegleCategorisation.objects.exists()


def test_recherche_dans_les_operations(client, alice):
    compte = FabriqueCompte(foyer=alice.foyer)
    FabriqueOperation(compte=compte, libelle="Prélèvement – AXA", libelle_banque="DE: AXA ID: 1")
    FabriqueOperation(compte=compte, libelle="Courses", note="anniversaire de Léa")
    FabriqueOperation(compte=compte, libelle="Boulangerie")

    def libelles(texte):
        reponse = client.get(reverse("banque:operations"), {"recherche": texte})
        return {operation.libelle for operation in reponse.context["operations"]}

    assert libelles("axa") == {"Prélèvement – AXA"}
    assert libelles("anniversaire") == {"Courses"}
