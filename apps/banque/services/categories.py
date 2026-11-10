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
