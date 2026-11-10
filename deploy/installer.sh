#!/usr/bin/env bash
# Installe ou met à jour Maison sur un serveur Debian/Ubuntu déjà équipé de nginx.
#
#   sudo DOMAINE=maison.example.org /opt/maison/deploy/installer.sh
#
# Idempotent : relancé après un `git pull`, il met à jour les dépendances, la feuille de style,
# les migrations et les fichiers statiques, puis redémarre le service. Il ne remplace jamais
# un fichier de configuration existant (/etc/maison/*, site nginx) : il le signale seulement.
# Les autres sites nginx du serveur ne sont pas touchés.
set -euo pipefail

APP="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOMAINE="${DOMAINE:-}"
PORT="${PORT:-8010}"
UTILISATEUR=maison
BASE=maison
CONFIG=/etc/maison
DONNEES=/var/lib/maison
MEDIA="$DONNEES/media"
VERSION_TAILWIND=4.3.5

etape() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
note() { printf '    %s\n' "$*"; }
erreur() { printf '\033[31mErreur : %s\033[0m\n' "$*" >&2; exit 1; }
aleatoire() { head -c "$1" /dev/urandom | od -An -tx1 | tr -d ' \n'; }
comme_postgres() { (cd /tmp && runuser -u postgres -- "$@"); }

[[ $EUID -eq 0 ]] || erreur "lancer avec sudo."
command -v apt-get >/dev/null || erreur "ce script vise Debian ou Ubuntu (apt)."
command -v nginx >/dev/null || erreur "nginx est introuvable sur ce serveur."

etape "Paquets système"
manquants=()
command -v psql >/dev/null || manquants+=(postgresql)
command -v restic >/dev/null || manquants+=(restic)
command -v curl >/dev/null || manquants+=(curl)
command -v rsync >/dev/null || manquants+=(rsync)
if ((${#manquants[@]})); then
    apt-get update -q
    apt-get install -y -q "${manquants[@]}"
else
    note "déjà installés"
fi
systemctl enable --now postgresql >/dev/null

etape "Utilisateur et dossiers"
id "$UTILISATEUR" >/dev/null 2>&1 \
    || useradd --system --home-dir "$DONNEES" --shell /usr/sbin/nologin "$UTILISATEUR"
install -d -m 0750 -o root -g "$UTILISATEUR" "$CONFIG"
install -d -m 0750 -o "$UTILISATEUR" -g "$UTILISATEUR" "$DONNEES" "$MEDIA"
install -d -m 0700 -o root -g root "$DONNEES/sauvegarde"

etape "uv (gestionnaire Python)"
if ! command -v uv >/dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh
fi
uv --version

etape "Base PostgreSQL et configuration"
if [[ ! -f "$CONFIG/maison.env" ]]; then
    [[ -n "$DOMAINE" ]] || erreur "première installation : préciser DOMAINE=..."
    mot_de_passe="$(aleatoire 24)"
    if comme_postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$UTILISATEUR'" | grep -q 1; then
        comme_postgres psql -qc "ALTER ROLE $UTILISATEUR WITH LOGIN PASSWORD '$mot_de_passe'"
    else
        comme_postgres psql -qc "CREATE ROLE $UTILISATEUR WITH LOGIN PASSWORD '$mot_de_passe'"
    fi
    umask 027
    cat >"$CONFIG/maison.env" <<EOF
# Généré par installer.sh le $(date -I). Voir .env.example pour le détail de chaque variable.
SECRET_KEY=$(aleatoire 50)
DEBUG=False
ALLOWED_HOSTS=$DOMAINE
CSRF_TRUSTED_ORIGINS=https://$DOMAINE
DATABASE_URL=postgres://$UTILISATEUR:$mot_de_passe@localhost:5432/$BASE
MEDIA_ROOT=$MEDIA
TAILLE_MAX_DOCUMENT_MO=10
# À renseigner pour les invitations et la réinitialisation des mots de passe
# (sans EMAIL_HOST, les e-mails ne partent pas : ils s'écrivent dans journalctl -u maison) :
# EMAIL_HOST=smtp-relay.brevo.com
# EMAIL_PORT=587
# EMAIL_HOST_USER=identifiant
# EMAIL_HOST_PASSWORD=cle-smtp
# EMAIL_USE_TLS=true
DEFAULT_FROM_EMAIL=Maison <maison@$DOMAINE>
INSCRIPTION_OUVERTE=True
DERRIERE_PROXY=True
DOUBLE_AUTH_OBLIGATOIRE=True
# Adresse de l'admin Django, volontairement imprévisible.
ADMIN_CHEMIN=gestion-$(aleatoire 6)/
EOF
    umask 022
    chown root:"$UTILISATEUR" "$CONFIG/maison.env"
    note "créé : $CONFIG/maison.env"
else
    note "conservé : $CONFIG/maison.env"
fi
if ! comme_postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$BASE'" | grep -q 1; then
    comme_postgres createdb --owner="$UTILISATEUR" --encoding=UTF8 --template=template0 "$BASE"
    note "base $BASE créée"
fi
ln -sfn "$CONFIG/maison.env" "$APP/.env"

etape "Dépendances Python"
# Python est installé par uv dans le dossier de l'application : il ne dépend pas de la
# version fournie par la distribution (Debian 12 n'a que Python 3.11).
export UV_PYTHON_INSTALL_DIR="$APP/.python" UV_PYTHON_PREFERENCE=only-managed
export UV_CACHE_DIR=/var/cache/maison-uv
(cd "$APP" && uv sync --frozen --no-dev)

etape "Feuille de style"
# Exécutable autonome de Tailwind : pas besoin de Node sur le serveur.
case "$(uname -m)" in
    x86_64) architecture=x64 ;;
    aarch64) architecture=arm64 ;;
    *) erreur "architecture non prise en charge : $(uname -m)" ;;
esac
tailwind="$APP/.outils/tailwindcss-$VERSION_TAILWIND"
if [[ ! -x "$tailwind" ]]; then
    install -d "$APP/.outils"
    curl -fsSL -o "$tailwind" \
        "https://github.com/tailwindlabs/tailwindcss/releases/download/v$VERSION_TAILWIND/tailwindcss-linux-$architecture"
    chmod +x "$tailwind"
fi
(cd "$APP" && "$tailwind" -i assets/css/app.css -o static/css/app.css --minify)

etape "Base de données et fichiers statiques"
gerer() { (cd "$APP" && runuser -u "$UTILISATEUR" -- "$APP/.venv/bin/python" manage.py "$@"); }
# collectstatic écrit dans le dossier de l'application, qui appartient à root.
(cd "$APP" && "$APP/.venv/bin/python" manage.py collectstatic --noinput -v 0)
gerer migrate --noinput
gerer createcachetable
gerer check --deploy --fail-level WARNING || note "avertissements ci-dessus à examiner"

etape "Services systemd"
for unite in "$APP"/deploy/systemd/*.{service,timer}; do
    sed -e "s|@APP@|$APP|g" -e "s|@PORT@|$PORT|g" -e "s|@MEDIA@|$MEDIA|g" "$unite" \
        >"/etc/systemd/system/$(basename "$unite")"
done
systemctl daemon-reload
systemctl enable maison.service maison-nettoyage.timer >/dev/null
systemctl restart maison.service
systemctl start maison-nettoyage.timer
if [[ -f "$CONFIG/sauvegarde.env" ]]; then
    systemctl enable --now maison-sauvegarde.timer >/dev/null
else
    note "sauvegardes non activées : voir docs/sauvegarde-restauration.md"
fi

etape "Site nginx"
if [[ -d /etc/nginx/sites-available ]]; then
    site=/etc/nginx/sites-available/maison
else
    site=/etc/nginx/conf.d/maison.conf
fi
if [[ -f "$site" ]]; then
    note "conservé : $site (comparer avec deploy/nginx/maison.conf après une mise à jour)"
else
    [[ -n "$DOMAINE" ]] || erreur "préciser DOMAINE=... pour créer le site nginx."
    sed -e "s|@DOMAINE@|$DOMAINE|g" -e "s|@PORT@|$PORT|g" "$APP/deploy/nginx/maison.conf" >"$site"
    [[ -d /etc/nginx/sites-enabled ]] && ln -sfn "$site" /etc/nginx/sites-enabled/maison
    note "créé : $site"
    note "HTTPS : sudo certbot --nginx -d $DOMAINE"
fi
nginx -t
systemctl reload nginx

etape "Vérification"
# Django refuse un nom d'hôte absent de ALLOWED_HOSTS : on se présente sous le premier.
hote="$(sed -n 's/^ALLOWED_HOSTS=//p' "$CONFIG/maison.env" | cut -d, -f1)"
sante() { curl -fsS -H "Host: $hote" "http://127.0.0.1:$PORT/sante/"; }
for _ in 1 2 3 4 5 6 7 8 9 10; do
    sante >/dev/null 2>&1 && break
    sleep 1
done
sante && echo
gerer verifier_sante
note "Compte administrateur : cd $APP && sudo -u $UTILISATEUR .venv/bin/python manage.py createsuperuser"
