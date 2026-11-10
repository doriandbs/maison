import re

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.documents import services
from apps.documents.models import chemin_document

from .fabriques import PDF_MINIMAL, PNG_MINIMAL, FabriqueDocument

pytestmark = pytest.mark.django_db


class TestDetecterType:
    @pytest.mark.parametrize(
        ("entete", "attendu"),
        [
            (PDF_MINIMAL, "application/pdf"),
            (b"\r\n%PDF-1.7", "application/pdf"),
            (PNG_MINIMAL, "image/png"),
            (b"\xff\xd8\xff\xe0\x00\x10JFIF", "image/jpeg"),
            (b"RIFF\x24\x00\x00\x00WEBPVP8 ", "image/webp"),
            (b"<html><script>alert(1)</script>", None),
            (b"GIF89a", None),
            (b"", None),
        ],
    )
    def test_reconnait_le_type_au_contenu(self, entete, attendu):
        assert services.detecter_type(entete) == attendu


class TestVerifierFichier:
    def test_le_nom_et_le_type_annonces_ne_comptent_pas(self):
        deguise = SimpleUploadedFile("facture.pdf", b"<html>piege</html>", "application/pdf")

        with pytest.raises(services.FichierRefuse):
            services.verifier_fichier(deguise)

    def test_une_image_nommee_pdf_est_reconnue_comme_image(self):
        fichier = SimpleUploadedFile("scan.pdf", PNG_MINIMAL, "application/pdf")

        assert services.verifier_fichier(fichier) == "image/png"
        assert fichier.tell() == 0

    def test_taille_maximale(self, settings):
        settings.TAILLE_MAX_DOCUMENT = 1024 * 1024
        trop_gros = SimpleUploadedFile("gros.pdf", PDF_MINIMAL + b"0" * 1024 * 1024)

        with pytest.raises(services.FichierRefuse, match="1 Mo"):
            services.verifier_fichier(trop_gros)


class TestCheminDocument:
    def test_nom_regenere_et_extension_issue_du_type_detecte(self):
        document = FabriqueDocument.build(foyer__id=7, type_mime="image/jpeg")

        chemin = chemin_document(document, "../../etc/passwd.exe")

        assert re.fullmatch(r"documents/7/[0-9a-f]{32}\.jpg", chemin)


class TestStockage:
    def test_le_fichier_est_range_dans_le_dossier_du_foyer(self, medias):
        document = FabriqueDocument()

        assert document.fichier.name.startswith(f"documents/{document.foyer_id}/")
        assert (medias / document.fichier.name).read_bytes() == PDF_MINIMAL

    def test_supprimer_efface_le_fichier(self, medias, django_capture_on_commit_callbacks):
        document = FabriqueDocument()
        chemin = medias / document.fichier.name

        with django_capture_on_commit_callbacks(execute=True):
            services.supprimer_document(document)

        assert not chemin.exists()

    def test_remplacer_efface_l_ancien_fichier(self, medias, django_capture_on_commit_callbacks):
        document = FabriqueDocument()
        ancien = medias / document.fichier.name
        nouveau = SimpleUploadedFile("photo.png", PNG_MINIMAL)

        with django_capture_on_commit_callbacks(execute=True):
            services.attacher_fichier(document, nouveau, "image/png")
            services.enregistrer_document(
                document, ancien_chemin=str(ancien.relative_to(medias).as_posix())
            )

        assert not ancien.exists()
        assert (medias / document.fichier.name).read_bytes() == PNG_MINIMAL
        assert (document.type_mime, document.nom_fichier) == ("image/png", "photo.png")
