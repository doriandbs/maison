from datetime import date

import factory
from django.core.files.base import ContentFile
from factory.django import DjangoModelFactory

from apps.documents.models import Document, TypeDocument
from apps.foyers.tests.fabriques import FabriqueFoyer

PDF_MINIMAL = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
PNG_MINIMAL = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


class FabriqueDocument(DjangoModelFactory):
    class Meta:
        model = Document

    foyer = factory.SubFactory(FabriqueFoyer)
    titre = factory.Sequence(lambda n: f"Document {n}")
    type = TypeDocument.FACTURE
    date = date(2026, 3, 1)
    type_mime = "application/pdf"
    nom_fichier = "facture.pdf"
    taille = len(PDF_MINIMAL)
    fichier = factory.LazyFunction(lambda: ContentFile(PDF_MINIMAL, name="facture.pdf"))
