#!/usr/bin/env bash
# Sauvegarde Maison : export de la base + documents, envoyés par restic vers chaque dépôt
# activé dans /etc/maison/sauvegarde.env. Lancé chaque nuit par maison-sauvegarde.timer.
#
#   sudo deploy/sauvegarde/sauvegarde.sh
#
# Un dépôt en échec n'empêche pas les autres ; le code de sortie est alors non nul
# (visible dans `systemctl status maison-sauvegarde`).
set -euo pipefail
# shellcheck source=commun.sh
. "$(dirname "${BASH_SOURCE[0]}")/commun.sh"
charger_configuration

mapfile -t depots < <(depots_actifs)
((${#depots[@]})) || erreur "aucun dépôt activé (DEPOT_S3, DEPOT_NAS)."

install -d -m 0700 "$DOSSIER_TRAVAIL"
export_base="$DOSSIER_TRAVAIL/base.dump"
journal "export de la base $BASE"
# Format « custom » : compressé, restaurable table par table avec pg_restore.
comme_postgres pg_dump --format=custom --no-owner --no-privileges "$BASE" >"$export_base.tmp"
mv "$export_base.tmp" "$export_base"

echecs=0
for depot in "${depots[@]}"; do
    nom="${depot%% *}"
    url="${depot#* }"
    journal "[$nom] début"
    if ! restic -r "$url" cat config >/dev/null 2>&1; then
        journal "[$nom] dépôt absent : initialisation"
        restic -r "$url" init || { journal "[$nom] ÉCHEC init"; echecs=$((echecs + 1)); continue; }
    fi
    # $CONSERVER volontairement sans guillemets : il contient plusieurs options.
    # shellcheck disable=SC2086
    if restic -r "$url" backup --tag maison --host maison "$export_base" "$MEDIA_ROOT" \
        && restic -r "$url" forget --tag maison --host maison $CONSERVER --prune; then
        # Contrôle d'intégrité le dimanche, sur un échantillon des données pour rester rapide.
        if [[ "$(date +%u)" == 7 ]]; then
            restic -r "$url" check --read-data-subset=5% || { journal "[$nom] ÉCHEC check"; echecs=$((echecs + 1)); continue; }
        fi
        journal "[$nom] terminé"
    else
        journal "[$nom] ÉCHEC"
        echecs=$((echecs + 1))
    fi
done

((echecs == 0)) || erreur "$echecs dépôt(s) en échec."
journal "sauvegarde terminée"
