# Maison

Gestion domestique multi-foyers : comptes, budget, documents. Django 5.2, PostgreSQL 16,
templates + Tailwind.

## Installation locale

Prérequis : Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 20+, PostgreSQL 16 avec une base
et un rôle `maison`.

```sh
uv sync                                   # dépendances Python dans .venv
npm install && npm run css                # feuille de style Tailwind
cp .env.example .env                      # puis renseigner SECRET_KEY et DATABASE_URL
uv run manage.py migrate && uv run manage.py createcachetable
uv run manage.py runserver
```

La base doit être en UTF-8. Si le serveur PostgreSQL a un autre encodage par défaut (WIN1252 sur
certaines installations Windows) : `CREATE DATABASE maison OWNER maison TEMPLATE template0 ENCODING 'UTF8';`

Les e-mails (invitations, réinitialisation du mot de passe) s'affichent dans la console en développement.
`uv run manage.py createsuperuser` donne accès à `/admin/`.

## Variables d'environnement

Voir [.env.example](.env.example), commenté. Les secrets ne viennent que de l'environnement.

## Tests et qualité

```sh
uv run pytest --cov          # tests + couverture
uv run ruff check . && uv run ruff format --check .
uv run mypy apps config
```

Les tests utilisent la base désignée par `DATABASE_URL`. Sans PostgreSQL sous la main :
`DATABASE_URL=sqlite:///:memory: uv run pytest`.

## Supervision

- `GET /sante/` : 200 si la base répond, 503 sinon.
- `uv run manage.py verifier_sante` : échoue si la base est injoignable ou une migration manque.

## Documentation

Les décisions structurantes sont dans [docs/adr/](docs/adr/).
