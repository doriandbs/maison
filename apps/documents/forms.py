from typing import Any

from django import forms
from django.core.files.uploadedfile import UploadedFile
from django.utils.translation import gettext_lazy as _

from apps.banque.forms import ChampDate
from apps.socle.forms import FormulaireDeFoyer

from . import services
from .models import Document, TypeDocument


class FormulaireDocument(FormulaireDeFoyer):
    fichier = forms.FileField(
        label=_("Fichier"),
        help_text=_("PDF, PNG, JPEG ou WebP."),
        widget=forms.ClearableFileInput(
            attrs={"accept": "application/pdf,image/png,image/jpeg,image/webp"}
        ),
    )
    date = ChampDate(label=_("Date du document"))
    echeance = ChampDate(label=_("Échéance"), required=False)
    paye_le = ChampDate(
        label=_("Payée le"), required=False, help_text=_("Laissez vide si elle reste à payer.")
    )

    class Meta:
        model = Document
        fields = (
            "fichier",
            "titre",
            "type",
            "emetteur",
            "date",
            "montant",
            "echeance",
            "paye_le",
            "note",
        )
        # Les documents appartiennent au foyer et ne sont reliés à aucun compte ni opération :
        # les finances sont personnelles (ADR 0006).
        widgets = {"note": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.type_mime: str | None = None
        self.ancien_chemin: str | None = self.instance.fichier.name or None
        if self.instance.pk:
            self.fields["fichier"].required = False
            self.fields["fichier"].help_text = _(
                "Actuel : %(nom)s. Choisissez un fichier seulement pour le remplacer."
            ) % {"nom": self.instance.nom_fichier}

    def clean_fichier(self) -> UploadedFile | None:
        fichier = self.cleaned_data.get("fichier")
        if not isinstance(fichier, UploadedFile):
            return None
        try:
            self.type_mime = services.verifier_fichier(fichier)
        except services.FichierRefuse as erreur:
            raise forms.ValidationError(str(erreur)) from erreur
        return fichier

    def clean(self) -> dict[str, Any]:
        donnees = super().clean() or {}
        if donnees.get("type") != TypeDocument.FACTURE:
            donnees["paye_le"] = None
        return donnees

    def _post_clean(self) -> None:
        # Le fichier est posé avant la validation du modèle pour que `full_clean`
        # voie un document complet.
        fichier = self.cleaned_data.get("fichier")
        if fichier and self.type_mime:
            services.attacher_fichier(self.instance, fichier, self.type_mime)
        super()._post_clean()  # type: ignore[misc]

    def save(self, commit: bool = True) -> Document:
        if not commit:
            raise NotImplementedError("Enregistrer via services.enregistrer_document.")
        document = super().save(commit=False)
        services.enregistrer_document(document, ancien_chemin=self.ancien_chemin)
        self.save_m2m()
        return document


class FormulaireFiltreDocuments(forms.Form):
    recherche = forms.CharField(
        label=_("Rechercher"),
        required=False,
        max_length=100,
        widget=forms.TextInput(attrs={"placeholder": _("Titre ou émetteur")}),
    )
    type = forms.ChoiceField(
        label=_("Type"),
        required=False,
        choices=[("", _("Tous les types")), *TypeDocument.choices],
    )
    a_payer = forms.BooleanField(label=_("Factures à payer seulement"), required=False)
