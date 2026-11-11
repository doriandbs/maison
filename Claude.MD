# Projet « Maison » — outil web de gestion domestique

## Contexte et objectif
Tu développes une application web de gestion quotidienne d'un foyer : factures et documents,
comptes bancaires, budget mensuel avec récap annuel automatique, charges récurrentes, prêts.
L'application est **multi-foyers** : un utilisateur peut créer son foyer, y inviter d'autres
membres, et un même déploiement peut servir plusieurs foyers indépendants et étanches.
Elle sera auto-hébergée sur un petit VPS (1 vCPU, 2 Go RAM) derrière Caddy.

Je suis développeur expérimenté (Java, Angular, SQL) mais débutant en Python/Django :
explique les choix idiomatiques Django quand ils diffèrent de ce qu'on ferait en Java/Spring,
sans sur-commenter le code lui-même.

## Stack imposée
TOUT EN FRANCAIS
- Python 3.12+, Django 5.x LTS, PostgreSQL 16, gestion des dépendances avec `uv` (ou `pip-tools`), fichier `pyproject.toml`
- Front : templates Django + HTMX + Alpine.js + Tailwind CSS (compilé en build, pas de CDN en prod). Pas de SPA.
- Formulaires : `django-crispy-forms` ou rendu manuel propre, au choix mais cohérent
- Tâches planifiées : commandes `manage.py` lancées par cron/systemd timers. **Pas de Celery, pas de Redis.**
- Serveur : gunicorn + Caddy en reverse proxy (Caddy gère TLS). Fichiers statiques via WhiteNoise.
- Config par variables d'environnement (`django-environ`), fichier `.env.example` à jour.
- Qualité : `ruff` (lint + format), `mypy` en mode progressif, `pre-commit`, `pytest` + `pytest-django` + `factory_boy`.

## Architecture
- Projet découpé en apps Django à responsabilité unique, dans `apps/` :
  `accounts` (users, auth), `households` (foyers, membres, invitations), `banking` (comptes, opérations,
  catégories), `budget` (tableaux mensuels, récap annuel, prévisionnel), `recurring` (charges récurrentes),
  `loans` (prêts, amortissement), `documents` (factures, contrats, fichiers), `notifications`, `dashboard`.
- Règle d'or : **toute donnée métier est rattachée à un `Household`**. Toute vue, queryset et formulaire
  filtre par le foyer courant de l'utilisateur. Centraliser cela (mixin de vue + manager de modèle
  `HouseholdScopedManager`) pour qu'un oubli soit impossible, et le tester explicitement.
- Logique métier dans des services/fonctions pures (ex. `loans/services/amortization.py`), pas dans les vues
  ni dans les templates. Les vues orchestrent, les modèles portent l'état, les services calculent.
- Montants en `DecimalField(max_digits=12, decimal_places=2)`, jamais en float. Dates en `DateField`,
  timestamps timezone-aware, `TIME_ZONE = "Europe/Paris"`.
- Soft delete / archivage pour les comptes et catégories (l'historique ne doit jamais casser).
- Migrations propres, nommées, une par changement logique.
- i18n activée, textes en français via `gettext` (permet une traduction plus tard).

## Modèle fonctionnel (à affiner ensemble avant le code)
- **Household** : nom, membres via `Membership(user, household, role ∈ {owner, admin, member, viewer})`,
  invitations par email avec token à expiration.
- **Account** : nom, type (courant, joint, livret, assurance vie, PEA, CTO, PER, épargne salariale, crypto,
  espèces, autre), établissement, titulaires, drapeau épargne/placement, solde initial, archivé.
  `BalanceSnapshot(account, date, amount)` pour l'historique et la vue patrimoine.
- **Category / Subcategory** : par foyer, jeu par défaut créé à la création du foyer, type revenu/dépense.
- **Transaction** : compte, date, libellé, montant signé, catégorie, note, pièce jointe optionnelle,
  `transfer_group` pour reconnaître les virements internes (non comptés en dépense).
  Import CSV/OFX bancaire avec détection de doublons + `CategorizationRule` (motif sur libellé → catégorie).
- **Budget** : tableau mensuel par compte et par catégorie (revenus, dépenses, virements, solde début/fin) ;
  **récap annuel calculé automatiquement** à partir des mois (par catégorie, par mois, par compte, taux
  d'épargne, N vs N‑1) ; budget prévisionnel par catégorie avec alertes de dépassement.
- **RecurringCharge** : libellé, montant, périodicité, jour, compte, catégorie, date de fin/reconduction ;
  génération des transactions prévues par commande planifiée ; rappel avant reconduction tacite.
- **Loan** : capital, taux, durée, mensualité, assurance, date de début, banque, compte débité ;
  tableau d'amortissement calculé, capital restant dû à date, simulation de remboursement anticipé.
- **Document** : fichier (PDF/image), type (facture, contrat, garantie, autre), fournisseur, date, montant,
  échéance, statut payé/à payer, catégorie, lien optionnel vers une Transaction et un Account ;
  `Supplier` avec numéro client et identifiants d'espace client **chiffrés** ; recherche plein texte
  (PostgreSQL `SearchVector`).
- **Dashboard** : soldes, reste à vivre, prochaines échéances, factures à payer, graphiques
  (dépenses par catégorie, évolution patrimoine). Graphes légers (Chart.js servi localement).
- **Notifications** : email (SMTP configurable) pour échéances, dépassements, rappels ; architecture
  permettant d'ajouter ntfy/Telegram plus tard.

## Versions
- **V1** : households + accounts + categories + transactions + tableau mensuel + récap annuel + documents simples + dashboard minimal + déploiement.
- **V2** : recurring + loans + import CSV/OFX + règles d'auto-catégorisation + notifications email.
- **V3** : suppliers/contrats avancés, snapshots patrimoine et graphiques, OCR optionnel, export complet du foyer.
Ne commence pas la V2 tant que la V1 n'est pas déployable et testée.

## Sécurité (non négociable)
- Isolation stricte entre foyers, testée par des tests d'accès croisés (un user du foyer A ne voit/modifie
  jamais une ressource du foyer B, y compris via URL devinée, HTMX partiel ou POST direct).
- Fichiers uploadés hors du dépôt (`MEDIA_ROOT` dédié), jamais servis directement : vue Django qui vérifie
  les droits puis `FileResponse`. Validation du type MIME réel, taille max, noms de fichiers régénérés (UUID).
- Mots de passe via les validateurs Django, 2FA TOTP optionnelle (`django-otp`), limitation de tentatives
  (`django-axes` ou équivalent), sessions sécurisées, CSRF partout, `SECURE_*` activés en prod, CSP raisonnable.
- Secrets uniquement via l'environnement. Identifiants fournisseurs chiffrés en base (clé hors base).

- Rate limiting sur login, inscription, invitation, mot de passe oublié.

## Qualité et clean code
- Code lisible, nommage explicite, fonctions courtes, pas de duplication, pas de logique dans les templates.
- Type hints partout, docstrings seulement quand elles apportent quelque chose.
- Tests : unitaires sur les services (amortissement, récap annuel, détection de virements, règles de
  catégorisation sont critiques et doivent être couverts à 100 %), tests de vues sur les permissions et
  l'isolation des foyers, factories plutôt que fixtures. Objectif ≥ 85 % de couverture sur le métier.

- `README.md` : installation locale en 5 commandes, variables d'env, lancement des tests.
- `docs/` : ADR courts pour les décisions structurantes, guide de déploiement, guide de sauvegarde/restauration.
- Accessibilité et responsive : utilisable sur téléphone, navigation clavier, contrastes corrects.
- Design : sobre, propre, cohérent ; une charte (couleurs, espacements, composants) définie une fois
  dans Tailwind et réutilisée. Pas d'UI « générée » incohérente d'une page à l'autre.

## Déploiement et exploitation (à livrer dès la V1)
- Dossier `deploy/` : `Caddyfile` d'exemple, unité systemd `gunicorn`, timers systemd pour les commandes
  planifiées, script d'installation idempotent documenté, `.env.example`.
- Commande `manage.py healthcheck` et endpoint `/health/` pour la supervision.
- Dossier `deploy/backup/` : script `backup.sh` qui fait `pg_dump` + archive de `MEDIA_ROOT`, puis envoie
  via **restic** vers **deux dépôts** : un bucket S3 (OVH/Scaleway/B2) et un **NAS local** (SFTP ou rclone).
  Rétention 7 quotidiens / 4 hebdo / 12 mensuels. Chaque dépôt est optionnel et activable par variables
  d'env. Fournir aussi `restore.sh` et une procédure de restauration testée, documentée pas à pas,
  de façon à pouvoir brancher ou changer une destination de sauvegarde sans toucher au code applicatif.

## Façon de travailler
1. Avant tout code : propose le découpage en apps, le modèle de données détaillé et les points
   d'incertitude. Pose-moi tes questions, puis attends ma validation.
2. Travaille par petites étapes livrables, chacune avec ses tests et ses migrations, commit atomique
   avec message conventionnel (`feat:`, `fix:`, `test:`, `chore:`).
3. À chaque étape, dis ce que tu as fait, ce qui reste, et les choix que tu as dû faire seul.
4. Ne contourne jamais une règle de sécurité ou d'isolation « pour aller plus vite ».
5. Si une bibliothèque tierce est ajoutée, justifie-la en une phrase et vérifie qu'elle est maintenue.

## Décisions validées (elles priment sur le texte ci-dessus en cas d'écart)
- Code en français, y compris les noms d'apps et de modèles : voir `docs/adr/0001-tout-en-francais.md`.
- Isolation des foyers, rôles, foyer principal : voir `docs/adr/0002-isolation-des-foyers.md`.
- Modèle fonctionnel de la V1 : voir `docs/adr/0003-modele-fonctionnel-v1.md`.
- Pas de Docker, ni en développement ni en production.
- nginx (déjà présent sur le VPS) à la place de Caddy : voir `docs/adr/0004-nginx-plutot-que-caddy.md`.
- Double authentification obligatoire pour tous : voir `docs/adr/0005-double-authentification.md`.
- Finances personnelles (comptes, budget, crédits), foyers partagés pour les documents et l'accès croisé : voir `docs/adr/0006-finances-personnelles.md`.