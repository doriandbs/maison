"""Chaque foyer partagé reçoit un classement commun (catégories, règles, budget), recopié de
l'espace de son propriétaire. Les opérations gardent leur catégorie : le budget du foyer les
range par nom de catégorie. Rien n'est supprimé.
"""

from django.db import migrations


def _cle(nom):
    return " ".join(nom.split()).casefold()


def recopier(apps, schema_editor):
    Foyer = apps.get_model("foyers", "Foyer")
    Adhesion = apps.get_model("foyers", "Adhesion")
    Categorie = apps.get_model("banque", "Categorie")
    Regle = apps.get_model("banque", "RegleCategorisation")
    LigneBudget = apps.get_model("budget", "LigneBudget")

    for foyer in Foyer.objects.filter(personne__isnull=True):
        if Categorie.objects.filter(foyer=foyer).exists():
            continue
        adhesions = Adhesion.objects.filter(foyer=foyer)
        responsable = (
            adhesions.filter(role="proprietaire").order_by("cree_le").first()
            or adhesions.order_by("cree_le").first()
        )
        source = Foyer.objects.filter(personne_id=responsable.utilisateur_id).first() if responsable else None
        if source is None:
            continue
        nouvelles = {}
        for parente in Categorie.objects.filter(foyer=source, parent__isnull=True):
            nouvelles[parente.pk] = Categorie.objects.create(
                foyer=foyer, nom=parente.nom, nature=parente.nature, archive_le=parente.archive_le
            )
        for sous in Categorie.objects.filter(foyer=source, parent__isnull=False):
            parente = nouvelles[sous.parent_id]
            nouvelles[sous.pk] = Categorie.objects.create(
                foyer=foyer, nom=sous.nom, nature=parente.nature, parent=parente,
                archive_le=sous.archive_le,
            )
        for regle in Regle.objects.filter(foyer=source):
            Regle.objects.create(foyer=foyer, motif=regle.motif, categorie=nouvelles[regle.categorie_id])
        for ligne in LigneBudget.objects.filter(foyer=source):
            LigneBudget.objects.create(
                foyer=foyer, categorie=nouvelles[ligne.categorie_id], mois=ligne.mois,
                montant=ligne.montant, ponctuel=ligne.ponctuel,
            )


class Migration(migrations.Migration):
    dependencies = [
        ("foyers", "0003_espaces_personnels_donnees"),
        ("prets", "0003_co_emprunteurs"),
    ]

    operations = [migrations.RunPython(recopier, migrations.RunPython.noop)]
