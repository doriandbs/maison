"""La migration 0003 range les finances existantes dans les espaces personnels, sans perte."""

from datetime import date
from decimal import Decimal as D

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

AVANT = "0002_espace_personnel"
APRES = "0003_espaces_personnels_donnees"


def _etat(migration_foyers):
    """Toutes les applications à jour, sauf `foyers` amenée à la migration indiquée."""
    executor = MigrationExecutor(connection)
    cibles = [n for n in executor.loader.graph.leaf_nodes() if n[0] != "foyers"]
    cibles.append(("foyers", migration_foyers))
    executor.migrate(cibles)
    executor.loader.build_graph()
    return executor.loader.project_state(cibles).apps


@pytest.mark.django_db(transaction=True)
def test_les_finances_d_un_foyer_passent_dans_l_espace_de_son_proprietaire():
    apps = _etat(AVANT)
    Utilisateur = apps.get_model("utilisateurs", "Utilisateur")
    Foyer = apps.get_model("foyers", "Foyer")
    Adhesion = apps.get_model("foyers", "Adhesion")
    Categorie = apps.get_model("banque", "Categorie")
    Compte = apps.get_model("banque", "Compte")
    Operation = apps.get_model("banque", "Operation")
    LigneBudget = apps.get_model("budget", "LigneBudget")
    Regle = apps.get_model("banque", "RegleCategorisation")
    Document = apps.get_model("documents", "Document")
    Pret = apps.get_model("prets", "Pret")

    dorian = Utilisateur.objects.create(email="dorian@example.org", first_name="Dorian")
    femme = Utilisateur.objects.create(email="alex@example.org", first_name="Alexandra")
    maison = Foyer.objects.create(nom="Maison", cree_par=dorian)
    proprio = Adhesion.objects.create(foyer=maison, utilisateur=dorian, role="proprietaire")
    Adhesion.objects.create(foyer=maison, utilisateur=femme, role="membre")
    alimentation = Categorie.objects.create(foyer=maison, nom="Alimentation", nature="depense")
    courses = Categorie.objects.create(
        foyer=maison, nom="Courses", nature="depense", parent=alimentation
    )
    compte = Compte.objects.create(
        foyer=maison, nom="Courant SG", solde_initial=D("100"), ouvert_le=date(2026, 1, 1)
    )
    compte.titulaires.set([proprio])
    operation = Operation.objects.create(
        foyer=maison,
        compte=compte,
        date=date(2026, 2, 1),
        libelle="Lidl",
        montant=D("-20"),
        categorie=courses,
    )
    LigneBudget.objects.create(
        foyer=maison, categorie=alimentation, mois=date(2026, 2, 1), montant=D("400")
    )
    Regle.objects.create(foyer=maison, motif="LIDL", categorie=courses)
    document = Document.objects.create(
        foyer=maison,
        titre="Facture",
        date=date(2026, 2, 1),
        fichier="documents/1/x.pdf",
        nom_fichier="x.pdf",
        type_mime="application/pdf",
        taille=1,
        compte=compte,
        operation=operation,
        categorie=courses,
    )
    pret = Pret.objects.create(
        foyer=maison,
        nom="Immo",
        capital=D("1000"),
        taux_annuel=D("1"),
        duree_mois=12,
        premiere_echeance=date(2026, 1, 1),
        compte=compte,
    )

    apps = _etat(APRES)
    Foyer = apps.get_model("foyers", "Foyer")
    espace = Foyer.objects.get(personne_id=dorian.pk)
    espace_femme = Foyer.objects.get(personne_id=femme.pk)

    def recharger(modele, objet):
        return apps.get_model(*modele).objects.get(pk=objet.pk)

    compte = recharger(("banque", "Compte"), compte)
    assert compte.foyer_id == espace.pk
    assert list(compte.titulaires.values_list("utilisateur_id", flat=True)) == [dorian.pk]
    operation = recharger(("banque", "Operation"), operation)
    assert operation.foyer_id == espace.pk and operation.categorie.foyer_id == espace.pk
    assert apps.get_model("budget", "LigneBudget").objects.get().foyer_id == espace.pk
    assert apps.get_model("banque", "RegleCategorisation").objects.get().foyer_id == espace.pk
    assert recharger(("prets", "Pret"), pret).foyer_id == espace.pk
    document = recharger(("documents", "Document"), document)
    assert document.foyer_id == maison.pk  # les papiers restent au foyer…
    assert (document.compte_id, document.operation_id, document.categorie_id) == (None, None, None)
    # … qui garde ses membres, et n'a plus de finances.
    assert apps.get_model("foyers", "Adhesion").objects.filter(foyer_id=maison.pk).count() == 2
    assert not apps.get_model("banque", "Compte").objects.filter(foyer_id=maison.pk).exists()
    # La seconde personne a un espace, avec les catégories par défaut.
    Categorie = apps.get_model("banque", "Categorie")
    assert Categorie.objects.filter(foyer_id=espace_femme.pk).count() > 10
    assert Categorie.objects.filter(foyer_id=espace.pk, nom="Courses").count() == 1
