"""Déplacer des comptes d'un foyer à un autre, avec tout ce qui en dépend.

Un compte n'appartient jamais qu'à un foyer : il est déplacé, pas copié. Suivent :
opérations, relevés de solde, documents qui s'y rattachent, crédits qu'il rembourse,
titulaires encore membres du foyer d'arrivée. Les catégories sont reprises par leur nom
(créées si besoin) ; les règles de catégorisation peuvent être recopiées.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.db import transaction
from django.db.models import Q

from apps.banque.models import Categorie, Compte, Operation, RegleCategorisation, ReleveSolde
from apps.banque.services.regles import normaliser
from apps.documents.models import Document
from apps.foyers.models import Adhesion, Foyer
from apps.prets.models import Pret, RemboursementAnticipe


class ErreurTransfert(ValueError):
    pass


class Correspondance:
    """Trouve (ou crée) dans le foyer d'arrivée la sous-catégorie de même nom."""

    def __init__(self, destination: Foyer, creer: bool) -> None:
        self.destination = destination
        self.creer = creer
        self.a_creer: list[str] = []
        categories = list(Categorie.objects.du_foyer(destination).select_related("parent"))
        self.parentes = {normaliser(c.nom): c for c in categories if c.parent_id is None}
        self.sous = {
            (normaliser(c.parent.nom), normaliser(c.nom)): c for c in categories if c.parent
        }

    def __call__(self, source: Categorie | None) -> Categorie | None:
        if source is None or source.parent is None:
            return None
        cle = (normaliser(source.parent.nom), normaliser(source.nom))
        if cle in self.sous:
            return self.sous[cle]
        if str(source) not in self.a_creer:
            self.a_creer.append(str(source))
        if not self.creer:
            return None
        parente = self.parentes.get(cle[0])
        if parente is None:
            parente = Categorie.objects.create(
                foyer=self.destination, nom=source.parent.nom, nature=source.parent.nature
            )
            self.parentes[cle[0]] = parente
        sous = Categorie.objects.create(
            foyer=self.destination, nom=source.nom, nature=parente.nature, parent=parente
        )
        self.sous[cle] = sous
        return sous


@dataclass
class Bilan:
    comptes: list[Compte]
    operations: int = 0
    releves: int = 0
    documents: int = 0
    prets: int = 0
    regles: int = 0
    # Virements internes dont l'autre compte reste : ils deviennent des opérations simples.
    virements_rompus: int = 0
    categories_creees: list[str] = field(default_factory=list)
    renommes: list[tuple[str, str]] = field(default_factory=list)


def _documents(source: Foyer, ids: list[int]) -> Q:
    return Q(foyer=source) & (Q(compte_id__in=ids) | Q(operation__compte_id__in=ids))


def _groupes_rompus(ids: list[int]) -> set:
    groupes = set(
        Operation.objects.filter(compte_id__in=ids)
        .exclude(groupe_virement=None)
        .values_list("groupe_virement", flat=True)
    )
    return set(
        Operation.objects.filter(groupe_virement__in=groupes)
        .exclude(compte_id__in=ids)
        .values_list("groupe_virement", flat=True)
    )


def _nom_libre(compte: Compte, source: Foyer, destination: Foyer) -> str:
    pris = set(Compte.objects.du_foyer(destination).values_list("nom", flat=True))
    if compte.nom not in pris:
        return compte.nom
    candidat = f"{compte.nom} ({source.nom})"[:100]
    numero = 2
    while candidat in pris:
        candidat = f"{compte.nom} ({source.nom} {numero})"[:100]
        numero += 1
    return candidat


def _verifier(comptes: list[Compte], source: Foyer, destination: Foyer) -> list[int]:
    if source.pk == destination.pk:
        raise ErreurTransfert("Choisissez un autre foyer que le foyer courant.")
    if not comptes:
        raise ErreurTransfert("Aucun compte choisi.")
    if any(compte.foyer_id != source.pk for compte in comptes):
        raise ErreurTransfert("Un compte n'appartient pas au foyer de départ.")
    return [compte.pk for compte in comptes]


def preparer(comptes: list[Compte], source: Foyer, destination: Foyer) -> Bilan:
    """Ce que le transfert va faire, sans rien modifier."""
    ids = _verifier(comptes, source, destination)
    operations = Operation.objects.filter(compte_id__in=ids).select_related("categorie__parent")
    correspondance = Correspondance(destination, creer=False)
    for operation in operations:
        correspondance(operation.categorie)
    for document in Document.objects.filter(_documents(source, ids)).select_related(
        "categorie__parent"
    ):
        correspondance(document.categorie)
    return Bilan(
        comptes=comptes,
        operations=operations.count(),
        releves=ReleveSolde.objects.filter(compte_id__in=ids).count(),
        documents=Document.objects.filter(_documents(source, ids)).count(),
        prets=Pret.objects.filter(foyer=source, compte_id__in=ids).count(),
        virements_rompus=len(_groupes_rompus(ids)),
        categories_creees=correspondance.a_creer,
        renommes=[
            (compte.nom, nom)
            for compte in comptes
            if (nom := _nom_libre(compte, source, destination)) != compte.nom
        ],
    )


@transaction.atomic
def transferer(
    comptes: list[Compte], source: Foyer, destination: Foyer, copier_regles: bool = True
) -> Bilan:
    ids = _verifier(comptes, source, destination)
    bilan = Bilan(comptes=comptes)
    correspondance = Correspondance(destination, creer=True)

    rompus = _groupes_rompus(ids)
    bilan.virements_rompus = len(rompus)
    Operation.objects.filter(groupe_virement__in=rompus).update(groupe_virement=None)

    operations = list(
        Operation.objects.filter(compte_id__in=ids).select_related("categorie__parent")
    )
    for operation in operations:
        operation.foyer = destination
        operation.categorie = correspondance(operation.categorie)
    Operation.objects.bulk_update(operations, ["foyer", "categorie"])
    bilan.operations = len(operations)

    bilan.releves = ReleveSolde.objects.filter(compte_id__in=ids).update(foyer=destination)

    documents = list(
        Document.objects.filter(_documents(source, ids)).select_related(
            "categorie__parent", "operation"
        )
    )
    for document in documents:
        document.foyer = destination
        document.categorie = correspondance(document.categorie)
        if document.compte_id not in ids:
            document.compte = None
        if document.operation is not None and document.operation.compte_id not in ids:
            document.operation = None
    Document.objects.bulk_update(documents, ["foyer", "categorie", "compte", "operation"])
    bilan.documents = len(documents)

    prets = Pret.objects.filter(foyer=source, compte_id__in=ids)
    RemboursementAnticipe.objects.filter(pret__in=prets).update(foyer=destination)
    bilan.prets = prets.update(foyer=destination)

    membres = {a.utilisateur_id: a for a in Adhesion.objects.filter(foyer=destination)}
    for compte in comptes:
        titulaires = [
            membres[a.utilisateur_id]
            for a in compte.titulaires.all()
            if a.utilisateur_id in membres
        ]
        nom = _nom_libre(compte, source, destination)
        if nom != compte.nom:
            bilan.renommes.append((compte.nom, nom))
        compte.nom = nom
        compte.foyer = destination
        compte.save(update_fields=["nom", "foyer", "modifie_le"])
        compte.titulaires.set(titulaires)

    if copier_regles:
        existants = {
            normaliser(m)
            for m in RegleCategorisation.objects.du_foyer(destination).values_list(
                "motif", flat=True
            )
        }
        for regle in RegleCategorisation.objects.du_foyer(source).select_related(
            "categorie__parent"
        ):
            categorie = correspondance(regle.categorie)
            if categorie is not None and normaliser(regle.motif) not in existants:
                RegleCategorisation.objects.create(
                    foyer=destination, motif=regle.motif, categorie=categorie
                )
                existants.add(normaliser(regle.motif))
                bilan.regles += 1

    bilan.categories_creees = correspondance.a_creer
    return bilan
