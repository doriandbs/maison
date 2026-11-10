# ADR 0004 – nginx plutôt que Caddy

Date : 2026-11-10 · Statut : accepté

## Contexte

Le cadrage initial prévoyait Caddy comme proxy inverse. Le VPS de production fait déjà tourner
nginx pour d'autres applications : deux serveurs ne peuvent pas écouter tous les deux sur les
ports 80 et 443.

## Décision

- Maison est un site nginx de plus (`deploy/nginx/maison.conf`), à côté des sites existants,
  qui ne sont pas touchés.
- Le HTTPS est géré comme pour les autres sites, par certbot (`certbot --nginx`), qui renouvelle
  le certificat tout seul.
- gunicorn écoute sur `127.0.0.1:<PORT>` (8010 par défaut, réglable à l'installation) plutôt que
  sur un socket Unix : pas de droits de fichier à accorder à nginx, et un port déjà pris par une
  autre application se change avec `PORT=` au moment de l'installation.
- Les fichiers statiques restent servis par WhiteNoise : une seule configuration nginx, rien à
  synchroniser entre les deux.

## Point de vigilance

nginx doit **écraser** `X-Forwarded-For` (`proxy_set_header X-Forwarded-For $remote_addr`) et non
y ajouter (`$proxy_add_x_forwarded_for`) : l'application lit la première adresse de cet en-tête
pour la limitation de débit et le verrouillage des connexions. En ajoutant, un client pourrait
choisir l'adresse prise en compte et contourner ces protections.
