from django.db import transaction
from django.utils import timezone

from apps.banque.models import Categorie, Nature
from apps.foyers.models import Foyer

# Pas de catégorie « Épargne » : alimenter un livret est un virement interne.
CATEGORIES_PAR_DEFAUT: dict[str, dict[str, list[str]]] = {
    Nature.DEPENSE: {
        "Logement": [
            "Loyer ou crédit",
            "Charges de copropriété",
            "Taxe foncière",
            "Assurance habitation",
            "Travaux",
        ],
        "Énergie": ["Électricité", "Gaz", "Eau", "Fioul et bois"],
        "Alimentation": ["Courses", "Restaurants", "Cantine"],
        "Transport": [
            "Carburant",
            "Assurance auto",
            "Entretien",
            "Péages et parking",
            "Transports en commun",
        ],
        "Abonnements": ["Internet", "Téléphone", "Streaming", "Logiciels"],
        "Enfants": ["Garde", "École", "Activités", "Vêtements"],
        "Santé": ["Mutuelle", "Médecin et pharmacie", "Optique et dentaire"],
        "Loisirs": ["Sorties", "Sport", "Vacances"],
        "Divers": ["Impôts", "Frais bancaires", "Cadeaux", "Autres dépenses"],
    },
    Nature.REVENU: {
        "Revenus": [
            "Salaire",
            "Primes",
            "Aides et allocations",
            "Remboursements",
            "Autres revenus",
        ],
    },
}


@transaction.atomic
def creer_categories_par_defaut(foyer: Foyer) -> None:
    for nature, arbre in CATEGORIES_PAR_DEFAUT.items():
        for nom_parent, noms_enfants in arbre.items():
            parent = Categorie.objects.create(foyer=foyer, nom=nom_parent, nature=nature)
            Categorie.objects.bulk_create(
                Categorie(foyer=foyer, nom=nom, nature=nature, parent=parent)
                for nom in noms_enfants
            )


@transaction.atomic
def basculer_archivage_categorie(categorie: Categorie) -> None:
    """Archiver une catégorie parente archive aussi ses sous-catégories."""
    if categorie.est_archivee:
        categorie.archive_le = None
    else:
        categorie.archive_le = timezone.now()
        categorie.sous_categories.filter(archive_le__isnull=True).update(
            archive_le=categorie.archive_le
        )
    categorie.save(update_fields=["archive_le", "modifie_le"])


@transaction.atomic
def copier_classement(source: Foyer, cible: Foyer) -> None:
    """Recopie catégories et règles de `source` dans `cible` (sans doublon de nom).

    À la création d'un foyer partagé : il part du classement de celui qui le crée,
    que tous les membres utiliseront ensuite.
    """
    from apps.banque.models import RegleCategorisation
    from apps.banque.services.regles import normaliser

    existantes: dict[tuple[str | None, str], Categorie] = {
        (normaliser(c.parent.nom) if c.parent else None, normaliser(c.nom)): c
        for c in Categorie.objects.filter(foyer=cible).select_related("parent")
    }
    correspondance: dict[int, Categorie] = {}
    for parente in Categorie.objects.filter(foyer=source, parent__isnull=True):
        cle: tuple[str | None, str] = (None, normaliser(parente.nom))
        if cle not in existantes:
            existantes[cle] = Categorie.objects.create(
                foyer=cible, nom=parente.nom, nature=parente.nature, archive_le=parente.archive_le
            )
        correspondance[parente.pk] = existantes[cle]
    for sous in Categorie.objects.filter(foyer=source, parent__isnull=False).select_related(
        "parent"
    ):
        parente = correspondance[sous.parent_id or 0]
        cle = (normaliser(parente.nom), normaliser(sous.nom))
        if cle not in existantes:
            existantes[cle] = Categorie.objects.create(
                foyer=cible,
                nom=sous.nom,
                nature=parente.nature,
                parent=parente,
                archive_le=sous.archive_le,
            )
        correspondance[sous.pk] = existantes[cle]
    motifs = {
        normaliser(m)
        for m in RegleCategorisation.objects.filter(foyer=cible).values_list("motif", flat=True)
    }
    for regle in RegleCategorisation.objects.filter(foyer=source):
        if normaliser(regle.motif) not in motifs:
            RegleCategorisation.objects.create(
                foyer=cible, motif=regle.motif, categorie=correspondance[regle.categorie_id]
            )
            motifs.add(normaliser(regle.motif))
