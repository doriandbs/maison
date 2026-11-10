# Sauvegardes et restauration

Chaque nuit, `maison-sauvegarde.timer` lance `deploy/sauvegarde/sauvegarde.sh`, qui :

1. exporte la base PostgreSQL (`pg_dump`, format compressé) ;
2. envoie cet export et le dossier des documents par **restic** vers chaque dépôt activé :
   un stockage objet S3 (OVH, Scaleway, Backblaze…) et/ou un NAS (SFTP ou rclone) ;
3. applique la rétention : 7 quotidiennes, 4 hebdomadaires, 12 mensuelles ;
4. le dimanche, vérifie l'intégrité d'un échantillon de 5 % des données.

restic chiffre tout côté serveur avant l'envoi et ne transmet que ce qui a changé.

## Mise en place

1. Créer le mot de passe de chiffrement, et **le recopier dans un gestionnaire de mots de passe**
   (sans lui, aucune restauration n'est possible, y compris pour vous) :
   ```sh
   sudo sh -c 'head -c 32 /dev/urandom | base64 > /etc/maison/restic.motdepasse; chmod 600 /etc/maison/restic.motdepasse'
   sudo cat /etc/maison/restic.motdepasse
   ```
2. Créer la configuration et y renseigner un ou deux dépôts :
   ```sh
   sudo install -m 600 /opt/maison/deploy/sauvegarde/sauvegarde.env.exemple /etc/maison/sauvegarde.env
   sudo nano /etc/maison/sauvegarde.env
   ```
   - **S3** : `DEPOT_S3`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` (créer le bucket et une clé
     limitée à ce bucket dans la console de l'hébergeur).
   - **NAS en SFTP** : `DEPOT_NAS=sftp:utilisateur@nas:/chemin`. root doit pouvoir s'y connecter
     par clé sans mot de passe : `sudo ssh-keygen -t ed25519` puis `sudo ssh-copy-id utilisateur@nas`.
   - **NAS par rclone** : `sudo apt install rclone && sudo rclone config`, puis
     `DEPOT_NAS=rclone:<remote>:<chemin>`.
3. Lancer une première sauvegarde à la main (elle initialise les dépôts) :
   ```sh
   sudo /opt/maison/deploy/sauvegarde/sauvegarde.sh
   ```
4. Activer la sauvegarde quotidienne :
   ```sh
   sudo systemctl enable --now maison-sauvegarde.timer
   ```
   (`installer.sh` le fait aussi dès que `/etc/maison/sauvegarde.env` existe.)

Changer de destination, en ajouter ou en retirer une : modifier `/etc/maison/sauvegarde.env`,
rien d'autre. Un dépôt vide est initialisé à la sauvegarde suivante.

Suivi : `systemctl status maison-sauvegarde` et `journalctl -u maison-sauvegarde`.

## Tester une restauration (à faire après la mise en place, puis tous les quelques mois)

Le mode essai restaure dans une base à part et un dossier temporaire, **sans toucher la
production** :

```sh
sudo /opt/maison/deploy/sauvegarde/restauration.sh nas --liste      # instantanés disponibles
sudo /opt/maison/deploy/sauvegarde/restauration.sh nas latest --essai
```

Il affiche le nombre de foyers, d'opérations et de documents restaurés et la date de la dernière
opération : comparer avec l'application. Faire de même avec `s3`. Nettoyer ensuite avec les
commandes indiquées à la fin de l'essai.

## Restaurer pour de bon

Après une perte de données, ou sur un serveur neuf.

1. Sur un serveur neuf : suivre [deploiement.md](deploiement.md) jusqu'à l'installation comprise,
   puis recréer `/etc/maison/sauvegarde.env` et `/etc/maison/restic.motdepasse` (depuis le
   gestionnaire de mots de passe). Pour le NAS en SFTP, autoriser la clé SSH du nouveau serveur.
2. Choisir l'instantané :
   ```sh
   sudo /opt/maison/deploy/sauvegarde/restauration.sh s3 --liste
   ```
3. Restaurer (`latest` ou l'identifiant choisi) :
   ```sh
   sudo /opt/maison/deploy/sauvegarde/restauration.sh s3 latest
   ```
   Le script demande de taper `RESTAURER`, arrête le service, conserve un export de la base
   actuelle dans `/var/lib/maison/sauvegarde/avant-restauration-*.dump`, remplace la base et les
   documents, applique les migrations, redémarre et vérifie l'état de l'application.
4. Se connecter et contrôler les dernières opérations et les derniers documents.

La clé `SECRET_KEY` n'a pas besoin d'être celle d'origine : changer de clé déconnecte seulement
les utilisateurs et invalide les liens d'invitation et de réinitialisation en cours.
