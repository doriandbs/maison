"""Crée l'espace financier personnel de chaque utilisateur et y range les finances des foyers.

Les comptes, opérations, relevés, catégories, budgets, règles et crédits d'un foyer partagé
passent dans l'espace de son propriétaire (le plus ancien s'il y en a plusieurs). Les
documents restent dans le foyer, détachés des comptes et opérations. Rien n'est supprimé.
"""

from django.db import migrations

from apps.banque.services.categories import CATEGORIES_PAR_DEFAUT


def _cle(nom):
    return " ".join(nom.split()).casefold()


def _espace(apps, utilisateur):
    Foyer = apps.get_model("foyers", "Foyer")
    Adhesion = apps.get_model("foyers", "Adhesion")
    espace = Foyer.objects.filter(personne=utilisateur).first()
    if espace is None:
        nom = utilisateur.first_name or utilisateur.email.split("@")[0]
        espace = Foyer.objects.create(
            nom=f"Finances de {nom}"[:100], personne=utilisateur, cree_par=utilisateur
        )
        Adhesion.objects.create(
            foyer=espace, utilisateur=utilisateur, role="proprietaire", est_principal=False
        )
    return espace


def _fusionner(apps, source, cible):
    Categorie = apps.get_model("banque", "Categorie")
    Compte = apps.get_model("banque", "Compte")
    Operation = apps.get_model("banque", "Operation")
    ReleveSolde = apps.get_model("banque", "ReleveSolde")
    Regle = apps.get_model("banque", "RegleCategorisation")
    LigneBudget = apps.get_model("budget", "LigneBudget")
    Document = apps.get_model("documents", "Document")
    Pret = apps.get_model("prets", "Pret")
    Remboursement = apps.get_model("prets", "RemboursementAnticipe")
    Adhesion = apps.get_model("foyers", "Adhesion")

    # Catégories : reprises par leur nom si elles existent déjà dans l'espace, déplacées sinon.
    remplacees = {}
    parentes_cible = {
        _cle(c.nom): c for c in Categorie.objects.filter(foyer=cible, parent__isnull=True)
    }
    for parente in Categorie.objects.filter(foyer=source, parent__isnull=True):
        existante = parentes_cible.get(_cle(parente.nom))
        if existante is None:
            parente.foyer = cible
            parente.save(update_fields=["foyer"])
            Categorie.objects.filter(parent=parente).update(foyer=cible)
            continue
        remplacees[parente.pk] = existante
        sous_cible = {_cle(c.nom): c for c in Categorie.objects.filter(parent=existante)}
        for sous in Categorie.objects.filter(parent=parente):
            if _cle(sous.nom) in sous_cible:
                remplacees[sous.pk] = sous_cible[_cle(sous.nom)]
            else:
                sous.foyer, sous.parent = cible, existante
                sous.save(update_fields=["foyer", "parent"])
    for ancienne, nouvelle in remplacees.items():
        Operation.objects.filter(categorie_id=ancienne).update(categorie=nouvelle)
        Regle.objects.filter(categorie_id=ancienne).update(categorie=nouvelle)
        for ligne in LigneBudget.objects.filter(categorie_id=ancienne):
            doublon = LigneBudget.objects.filter(
                categorie=nouvelle, mois=ligne.mois, ponctuel=ligne.ponctuel
            ).exists()
            if doublon:
                ligne.delete()
            else:
                ligne.categorie = nouvelle
                ligne.save(update_fields=["categorie"])

    # Comptes : un nom déjà pris dans l'espace est complété du nom du foyer d'origine.
    pris = set(Compte.objects.filter(foyer=cible).values_list("nom", flat=True))
    proprietaire = Adhesion.objects.get(foyer=cible, utilisateur_id=cible.personne_id)
    for compte in Compte.objects.filter(foyer=source):
        etait_titulaire = compte.titulaires.filter(utilisateur_id=cible.personne_id).exists()
        nom = compte.nom
        if nom in pris:
            nom = f"{compte.nom} ({source.nom})"[:100]
        pris.add(nom)
        compte.nom, compte.foyer = nom, cible
        compte.save(update_fields=["nom", "foyer"])
        compte.titulaires.set([proprietaire] if etait_titulaire else [])

    Operation.objects.filter(foyer=source).update(foyer=cible)
    ReleveSolde.objects.filter(foyer=source).update(foyer=cible)
    LigneBudget.objects.filter(foyer=source).update(foyer=cible)
    motifs = {_cle(m) for m in Regle.objects.filter(foyer=cible).values_list("motif", flat=True)}
    for regle in Regle.objects.filter(foyer=source):
        if _cle(regle.motif) in motifs:
            regle.delete()
        else:
            motifs.add(_cle(regle.motif))
            regle.foyer = cible
            regle.save(update_fields=["foyer"])
    Remboursement.objects.filter(foyer=source).update(foyer=cible)
    Pret.objects.filter(foyer=source).update(foyer=cible)
    # Les documents restent au foyer et ne sont plus reliés aux finances.
    Document.objects.filter(foyer=source).update(compte=None, operation=None, categorie=None)


def _categories_par_defaut(apps, espace):
    Categorie = apps.get_model("banque", "Categorie")
    for nature, arbre in CATEGORIES_PAR_DEFAUT.items():
        for nom_parent, noms in arbre.items():
            parent = Categorie.objects.create(foyer=espace, nom=nom_parent, nature=nature)
            for nom in noms:
                Categorie.objects.create(foyer=espace, nom=nom, nature=nature, parent=parent)


def migrer(apps, schema_editor):
    Utilisateur = apps.get_model("utilisateurs", "Utilisateur")
    Foyer = apps.get_model("foyers", "Foyer")
    Adhesion = apps.get_model("foyers", "Adhesion")
    Categorie = apps.get_model("banque", "Categorie")

    for utilisateur in Utilisateur.objects.all():
        _espace(apps, utilisateur)

    for foyer in Foyer.objects.filter(personne__isnull=True).order_by("pk"):
        adhesions = Adhesion.objects.filter(foyer=foyer)
        responsable = (
            adhesions.filter(role="proprietaire").order_by("cree_le").first()
            or adhesions.order_by("cree_le").first()
        )
        if responsable is not None:
            _fusionner(apps, foyer, _espace(apps, responsable.utilisateur))

    for espace in Foyer.objects.filter(personne__isnull=False):
        if not Categorie.objects.filter(foyer=espace).exists():
            _categories_par_defaut(apps, espace)


class Migration(migrations.Migration):
    dependencies = [
        ("foyers", "0002_espace_personnel"),
        ("banque", "0002_import_et_regles"),
        ("budget", "0001_ligne_budget"),
        ("documents", "0001_document"),
        ("prets", "0001_prets_et_remboursements"),
        ("utilisateurs", "0002_appareils_de_confiance"),
    ]

    operations = [migrations.RunPython(migrer, migrations.RunPython.noop)]
