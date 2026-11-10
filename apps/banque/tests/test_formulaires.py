from datetime import date
from decimal import Decimal

import pytest
from django import forms
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

from apps.banque.forms import (
    FormulaireCategorie,
    FormulaireCompte,
    FormulaireOperation,
    FormulaireVirement,
)
from apps.banque.models import Nature
from apps.foyers.models import Invitation
from apps.foyers.tests.fabriques import FabriqueAdhesion, FabriqueFoyer
from apps.socle.forms import FormulaireDeFoyer

from .fabriques import FabriqueCategorie, FabriqueCompte, FabriqueOperation, FabriqueSousCategorie

pytestmark = pytest.mark.django_db


def _donnees_operation(**surcharges):
    return {
        "date": "2026-03-15",
        "libelle": "Courses",
        "sens": "depense",
        "montant": "42.50",
        "note": "",
    } | surcharges


class TestFormulaireDeFoyer:
    """Le socle : un identifiant d'un autre foyer n'est jamais un choix valide."""

    def test_compte_d_un_autre_foyer_refuse(self):
        foyer = FabriqueFoyer()
        compte_etranger = FabriqueCompte()

        formulaire = FormulaireOperation(_donnees_operation(compte=compte_etranger.pk), foyer=foyer)

        assert not formulaire.is_valid()
        assert "compte" in formulaire.errors

    def test_categorie_d_un_autre_foyer_refusee(self):
        compte = FabriqueCompte()
        categorie_etrangere = FabriqueSousCategorie()

        formulaire = FormulaireOperation(
            _donnees_operation(compte=compte.pk, categorie=categorie_etrangere.pk),
            foyer=compte.foyer,
        )

        assert not formulaire.is_valid()
        assert "categorie" in formulaire.errors

    def test_titulaire_d_un_autre_foyer_refuse(self):
        foyer = FabriqueFoyer()
        etranger = FabriqueAdhesion()

        formulaire = FormulaireCompte(
            {
                "nom": "Courant",
                "type": "courant",
                "solde_initial": "0",
                "ouvert_le": "2026-01-01",
                "titulaires": [etranger.pk],
            },
            foyer=foyer,
        )

        assert not formulaire.is_valid()
        assert "titulaires" in formulaire.errors

    def test_parente_d_un_autre_foyer_refusee(self):
        formulaire = FormulaireCategorie(
            {"nom": "x", "nature": Nature.DEPENSE, "parent": FabriqueCategorie().pk},
            foyer=FabriqueFoyer(),
        )

        assert not formulaire.is_valid()
        assert "parent" in formulaire.errors

    def test_l_objet_cree_est_rattache_au_foyer_fourni(self):
        foyer = FabriqueFoyer()

        compte = FormulaireCompte(
            {"nom": "Courant", "type": "courant", "solde_initial": "10", "ouvert_le": "2026-01-01"},
            foyer=foyer,
        ).save()

        assert compte.foyer == foyer

    def test_refuse_de_modifier_l_objet_d_un_autre_foyer(self):
        with pytest.raises(ImproperlyConfigured):
            FormulaireCompte(instance=FabriqueCompte(), foyer=FabriqueFoyer())

    def test_refuse_un_champ_vers_un_modele_hors_foyer(self):
        class FormulaireFautif(FormulaireDeFoyer):
            class Meta:
                model = Invitation
                fields = ("email", "invite_par")

        with pytest.raises(ImproperlyConfigured):
            FormulaireFautif(foyer=FabriqueFoyer())

    def test_les_champs_ordinaires_ne_sont_pas_touches(self):
        class FormulaireSimple(FormulaireDeFoyer):
            class Meta:
                model = Invitation
                fields = ("email",)

        formulaire = FormulaireSimple(foyer=FabriqueFoyer())

        assert isinstance(formulaire.fields["email"], forms.EmailField)


class TestFormulaireOperation:
    def test_une_depense_est_stockee_en_negatif(self):
        compte = FabriqueCompte()
        categorie = FabriqueSousCategorie(parent__foyer=compte.foyer)

        operation = FormulaireOperation(
            _donnees_operation(compte=compte.pk, categorie=categorie.pk), foyer=compte.foyer
        ).save()

        assert operation.montant == Decimal("-42.50")
        assert (operation.foyer, operation.categorie) == (compte.foyer, categorie)

    def test_une_recette_est_stockee_en_positif(self):
        compte = FabriqueCompte()

        operation = FormulaireOperation(
            _donnees_operation(compte=compte.pk, sens="recette"), foyer=compte.foyer
        ).save()

        assert operation.montant == Decimal("42.50")

    def test_la_modification_reaffiche_montant_positif_et_sens(self):
        operation = FabriqueOperation(montant=Decimal("-12.00"))

        formulaire = FormulaireOperation(instance=operation, foyer=operation.foyer)

        assert formulaire.initial["montant"] == Decimal("12.00")
        assert formulaire.initial["sens"] == "depense"

    @pytest.mark.parametrize("montant", ["0", "-5"])
    def test_montant_nul_ou_negatif_refuse(self, montant):
        compte = FabriqueCompte()

        formulaire = FormulaireOperation(
            _donnees_operation(compte=compte.pk, montant=montant), foyer=compte.foyer
        )

        assert "montant" in formulaire.errors

    def test_date_anterieure_au_solde_initial_refusee(self):
        compte = FabriqueCompte(ouvert_le=date(2026, 3, 1))

        formulaire = FormulaireOperation(
            _donnees_operation(compte=compte.pk, date="2026-02-28"), foyer=compte.foyer
        )

        assert "date" in formulaire.errors

    def test_seules_les_sous_categories_actives_sont_proposees(self):
        parente = FabriqueCategorie()
        active = FabriqueSousCategorie(parent=parente)
        FabriqueSousCategorie(parent=parente, archive_le=timezone.now())

        formulaire = FormulaireOperation(foyer=parente.foyer)

        assert list(formulaire.fields["categorie"].queryset) == [active]

    def test_un_compte_archive_n_est_plus_propose_sauf_s_il_est_deja_utilise(self):
        archive = FabriqueCompte(archive_le=timezone.now())
        operation = FabriqueOperation(compte=archive)

        nouveau = FormulaireOperation(foyer=archive.foyer)
        modification = FormulaireOperation(instance=operation, foyer=archive.foyer)

        assert list(nouveau.fields["compte"].queryset) == []
        assert list(modification.fields["compte"].queryset) == [archive]


class TestFormulaireVirement:
    def _donnees(self, source, destination):
        return {
            "source": source.pk,
            "destination": destination.pk,
            "date": "2026-03-01",
            "montant": "100",
            "libelle": "Virement",
        }

    def test_valide_entre_deux_comptes_du_foyer(self):
        source = FabriqueCompte()
        destination = FabriqueCompte(foyer=source.foyer)

        assert FormulaireVirement(self._donnees(source, destination), foyer=source.foyer).is_valid()

    def test_destination_d_un_autre_foyer_refusee(self):
        source = FabriqueCompte()

        formulaire = FormulaireVirement(self._donnees(source, FabriqueCompte()), foyer=source.foyer)

        assert "destination" in formulaire.errors

    def test_meme_compte_refuse(self):
        source = FabriqueCompte()

        formulaire = FormulaireVirement(self._donnees(source, source), foyer=source.foyer)

        assert "destination" in formulaire.errors


class TestFormulaireCategorie:
    def test_seules_les_parentes_sont_proposees_comme_parent(self):
        sous_categorie = FabriqueSousCategorie()

        formulaire = FormulaireCategorie(foyer=sous_categorie.foyer)

        assert list(formulaire.fields["parent"].queryset) == [sous_categorie.parent]

    def test_une_categorie_ne_peut_pas_etre_sa_propre_parente(self):
        parente = FabriqueCategorie()

        formulaire = FormulaireCategorie(instance=parente, foyer=parente.foyer)

        assert parente not in formulaire.fields["parent"].queryset
