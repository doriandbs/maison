# Fonctions partagées par sauvegarde.sh et restauration.sh (à sourcer, pas à exécuter).

CONFIG_SAUVEGARDE="${CONFIG_SAUVEGARDE:-/etc/maison/sauvegarde.env}"

journal() { printf '%s %s\n' "$(date '+%F %T')" "$*"; }
erreur() { journal "ERREUR : $*" >&2; exit 1; }
comme_postgres() { (cd /tmp && runuser -u postgres -- "$@"); }

charger_configuration() {
    [[ $EUID -eq 0 ]] || erreur "lancer en root (sudo)."
    [[ -r "$CONFIG_SAUVEGARDE" ]] || erreur "configuration absente : $CONFIG_SAUVEGARDE"
    set -a
    # shellcheck source=/dev/null
    . "$CONFIG_SAUVEGARDE"
    set +a
    : "${BASE:?}" "${MEDIA_ROOT:?}" "${DOSSIER_TRAVAIL:?}" "${RESTIC_PASSWORD_FILE:?}"
    [[ -r "$RESTIC_PASSWORD_FILE" ]] || erreur "mot de passe restic introuvable : $RESTIC_PASSWORD_FILE"
    command -v restic >/dev/null || erreur "restic n'est pas installé."
}

# Affiche « nom url » pour chaque dépôt activé.
depots_actifs() {
    [[ -n "${DEPOT_S3:-}" ]] && echo "s3 $DEPOT_S3"
    [[ -n "${DEPOT_NAS:-}" ]] && echo "nas $DEPOT_NAS"
    return 0
}

url_du_depot() {
    case "$1" in
        s3) echo "${DEPOT_S3:-}" ;;
        nas) echo "${DEPOT_NAS:-}" ;;
        *) echo "" ;;
    esac
}
