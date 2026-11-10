#!/usr/bin/env bash
# Restauration Maison depuis un dépôt restic.
#
#   sudo deploy/sauvegarde/restauration.sh <s3|nas> [instantané] [--essai]
#
#   instantané : identifiant restic (voir `--liste`), « latest » par défaut.
#   --essai    : restaure dans une base à part (<base>_essai) et un dossier temporaire,
#                sans arrêter ni toucher la production. À faire régulièrement pour vérifier
#                que les sauvegardes sont exploitables.
#   --liste    : affiche les instantanés disponibles et s'arrête.
#
# Sans --essai : arrête le service, garde un export de la base actuelle par précaution,
# remplace la base et les documents, puis redémarre et vérifie.
set -euo pipefail
# shellcheck source=commun.sh
. "$(dirname "${BASH_SOURCE[0]}")/commun.sh"
APP="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

nom_depot="${1:-}"
instantane=latest
essai=false
liste=false
for argument in "${@:2}"; do
    case "$argument" in
        --essai) essai=true ;;
        --liste) liste=true ;;
        *) instantane="$argument" ;;
    esac
done

charger_configuration
url="$(url_du_depot "$nom_depot")"
[[ -n "$url" ]] || erreur "dépôt inconnu ou désactivé : « $nom_depot » (attendu : s3 ou nas)."

if $liste; then
    restic -r "$url" snapshots --tag maison
    exit 0
fi

zone="$(mktemp -d "$DOSSIER_TRAVAIL/restauration.XXXXXX")"
trap 'rm -rf "$zone"' EXIT
journal "extraction de l'instantané $instantane depuis $nom_depot"
restic -r "$url" restore "$instantane" --tag maison --target "$zone"
export_base="$zone$DOSSIER_TRAVAIL/base.dump"
medias="$zone$MEDIA_ROOT"
[[ -f "$export_base" ]] || erreur "export de la base absent de l'instantané."
[[ -d "$medias" ]] || erreur "dossier des documents absent de l'instantané."

# Recrée une base vide puis y charge l'export (objets attribués au rôle de l'application).
charger_base() {
    local cible="$1"
    comme_postgres dropdb --if-exists "$cible"
    comme_postgres createdb --owner=maison --encoding=UTF8 --template=template0 "$cible"
    # Lu par root et transmis sur l'entrée standard : postgres n'a pas accès au dossier de travail.
    comme_postgres pg_restore --no-owner --role=maison --exit-on-error -d "$cible" <"$export_base"
}

if $essai; then
    cible="${BASE}_essai"
    journal "ESSAI : chargement dans la base $cible"
    charger_base "$cible"
    copie_medias="$DOSSIER_TRAVAIL/essai-medias"
    rm -rf "$copie_medias"
    cp -a "$medias" "$copie_medias"
    journal "ESSAI réussi. Contrôles :"
    comme_postgres psql -d "$cible" -c \
        "SELECT (SELECT count(*) FROM foyers_foyer) AS foyers,
                (SELECT count(*) FROM banque_operation) AS operations,
                (SELECT count(*) FROM documents_document) AS documents,
                (SELECT max(date) FROM banque_operation) AS derniere_operation;"
    echo "Fichiers de documents restaurés : $(find "$copie_medias" -type f | wc -l) dans $copie_medias"
    echo "Nettoyage : sudo -u postgres dropdb $cible && sudo rm -rf $copie_medias"
    exit 0
fi

echo "La base « $BASE » et le dossier $MEDIA_ROOT vont être REMPLACÉS par l'instantané $instantane."
read -r -p "Taper RESTAURER pour confirmer : " reponse
[[ "$reponse" == RESTAURER ]] || erreur "abandon."

journal "arrêt du service"
systemctl stop maison.service maison-nettoyage.timer maison-sauvegarde.timer
precaution="$DOSSIER_TRAVAIL/avant-restauration-$(date +%Y%m%d-%H%M%S).dump"
comme_postgres pg_dump --format=custom --no-owner "$BASE" >"$precaution" \
    && journal "base actuelle conservée dans $precaution"

journal "restauration de la base"
charger_base "$BASE"
journal "restauration des documents"
rsync -a --delete "$medias/" "$MEDIA_ROOT/"
chown -R maison:maison "$MEDIA_ROOT"

journal "migrations éventuelles et redémarrage"
(cd "$APP" && runuser -u maison -- "$APP/.venv/bin/python" manage.py migrate --noinput)
systemctl start maison.service maison-nettoyage.timer
[[ -f /etc/systemd/system/timers.target.wants/maison-sauvegarde.timer ]] \
    && systemctl start maison-sauvegarde.timer
(cd "$APP" && runuser -u maison -- "$APP/.venv/bin/python" manage.py verifier_sante)
journal "restauration terminée"
