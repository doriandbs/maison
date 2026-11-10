from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction

from .models import EXTENSIONS_PAR_TYPE, Document

TAILLE_ENTETE = 1024


class FichierRefuse(ValueError):
    pass


def detecter_type(entete: bytes) -> str | None:
    """Type MIME d'après les premiers octets du fichier (« nombre magique »)."""
    if entete.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if entete.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if entete[:4] == b"RIFF" and entete[8:12] == b"WEBP":
        return "image/webp"
    # La norme tolère quelques octets avant l'en-tête d'un PDF.
    if b"%PDF-" in entete[:TAILLE_ENTETE]:
        return "application/pdf"
    return None


def verifier_fichier(fichier: UploadedFile) -> str:
    """Contrôle la taille et le type réel ; renvoie le type MIME détecté."""
    taille_max = settings.TAILLE_MAX_DOCUMENT
    if fichier.size is None or fichier.size > taille_max:
        raise FichierRefuse(f"Le fichier dépasse {taille_max // (1024 * 1024)} Mo.")
    fichier.seek(0)
    entete = fichier.read(TAILLE_ENTETE)
    fichier.seek(0)
    type_mime = detecter_type(entete)
    if type_mime not in EXTENSIONS_PAR_TYPE:
        raise FichierRefuse("Seuls les PDF et les images PNG, JPEG ou WebP sont acceptés.")
    return type_mime


def attacher_fichier(document: Document, fichier: UploadedFile, type_mime: str) -> None:
    """Pose le fichier sur le document (sans enregistrer) ; l'ancien sera supprimé à
    l'enregistrement par `enregistrer_document`."""
    document.fichier = fichier
    document.nom_fichier = (fichier.name or "document")[:255]
    document.type_mime = type_mime
    document.taille = fichier.size or 0


def enregistrer_document(document: Document, ancien_chemin: str | None = None) -> Document:
    document.save()
    if ancien_chemin and ancien_chemin != document.fichier.name:
        _supprimer_apres_validation(document, ancien_chemin)
    return document


def supprimer_document(document: Document) -> None:
    chemin = document.fichier.name
    document.delete()
    if chemin:
        _supprimer_apres_validation(document, chemin)


def _supprimer_apres_validation(document: Document, chemin: str) -> None:
    # Le fichier ne disparaît que si la transaction aboutit : jamais de ligne orpheline.
    stockage = document.fichier.storage
    transaction.on_commit(lambda: stockage.delete(chemin))
