# Mise en production

Cible : un VPS Debian 12 ou Ubuntu 22.04/24.04, avec nginx déjà installé (d'autres sites peuvent y
tourner, ils ne sont pas touchés). Voir l'[ADR 0004](adr/0004-nginx-plutot-que-caddy.md).

## Ce que fait l'installation

| Élément | Emplacement |
|---|---|
| Code de l'application (appartient à root, en lecture seule pour le service) | `/opt/maison` |
| Configuration (secrets) | `/etc/maison/maison.env` (lien `/opt/maison/.env`) |
| Documents déposés | `/var/lib/maison/media` |
| Service gunicorn | `maison.service`, sur `127.0.0.1:8010` |
| Purge des sessions | `maison-nettoyage.timer` (chaque nuit) |
| Sauvegardes | `maison-sauvegarde.timer` (chaque nuit, une fois configurées) |
| Site nginx | `/etc/nginx/sites-available/maison` (ou `conf.d/maison.conf`) |

Python 3.12 est installé par `uv` dans `/opt/maison/.python` : il ne dépend pas de la version de
la distribution. La feuille de style est compilée par l'exécutable autonome de Tailwind : pas
besoin de Node sur le serveur. PostgreSQL et restic sont installés depuis la distribution s'ils
manquent (Django 5.2 accepte PostgreSQL 14 et plus : la version 15 de Debian 12 convient).

## Première installation

1. Faire pointer le nom de domaine (enregistrement DNS A/AAAA) vers le VPS.
2. Récupérer le code :
   ```sh
   sudo git clone <url-du-depot> /opt/maison
   ```
3. Installer :
   ```sh
   sudo DOMAINE=maison.example.org /opt/maison/deploy/installer.sh
   ```
   Si le port 8010 est déjà utilisé par une autre application : ajouter `PORT=8020` (par exemple).
4. Activer le HTTPS, comme pour les autres sites du serveur :
   ```sh
   sudo certbot --nginx -d maison.example.org
   ```
   Tant que cette étape n'est pas faite, le site redirige vers une adresse HTTPS qui ne répond pas.
5. Renseigner l'envoi des e-mails (invitations, mot de passe oublié) dans
   `/etc/maison/maison.env` (`EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`,
   `EMAIL_USE_TLS`), puis `sudo systemctl restart maison`. Vérifier l'envoi avec
   `sudo -u maison .venv/bin/python manage.py sendtestemail votre@adresse.fr`.
6. Créer un compte administrateur (accès à l'admin, dont l'adresse est `ADMIN_CHEMIN` dans
   `/etc/maison/maison.env`) ; il devra configurer la double authentification à sa première
   connexion, comme tout le monde :
   ```sh
   cd /opt/maison && sudo -u maison .venv/bin/python manage.py createsuperuser
   ```
7. Configurer les sauvegardes : [sauvegarde-restauration.md](sauvegarde-restauration.md).

## Mise à jour

```sh
cd /opt/maison && sudo git pull && sudo ./deploy/installer.sh
```

Le script ne recrée ni la configuration ni le site nginx s'ils existent : il met à jour les
dépendances, la feuille de style, les fichiers statiques, applique les migrations et redémarre
le service. Si `deploy/nginx/maison.conf` a changé, reporter la modification à la main dans le
site nginx (certbot l'a modifié, on ne l'écrase donc pas).

## Double authentification perdue

Si quelqu'un a perdu à la fois son téléphone et ses codes de secours, **après avoir vérifié son
identité de vive voix** :

```sh
cd /srv/maison/maison && sudo -u maison .venv/bin/python manage.py retirer_double_auth adresse@exemple.fr
```

Il la reconfigurera à sa prochaine connexion. Personne ne peut le faire depuis le site.

## Supervision et diagnostic

- `GET https://maison.example.org/sante/` : 200 si la base répond, 503 sinon (à brancher sur
  un service de surveillance externe).
- `cd /opt/maison && sudo -u maison .venv/bin/python manage.py verifier_sante` : échoue aussi si
  une migration n'est pas appliquée.
- Journaux de l'application : `sudo journalctl -u maison -f`.
- Journaux nginx : `/var/log/nginx/maison.*.log`.
- Tâches planifiées : `systemctl list-timers 'maison-*'`.
