# ADR 0001 – Code en français

Date : 2026-11-10 · Statut : accepté

## Décision

Tout ce que nous nommons nous-mêmes est en français, sans accents dans les identifiants :
apps, modèles, champs, fonctions, variables, URL, noms de routes, tests, commits, documentation.

| Prévu dans CLAUDE.md | Nom retenu |
|---|---|
| `core` (ajoutée) | `socle` |
| `accounts` | `utilisateurs` |
| `households` | `foyers` |
| `banking` | `banque` |
| `budget` | `budget` |
| `recurring` | `recurrences` |
| `loans` | `prets` |
| `documents` | `documents` |
| `notifications` | `notifications` |
| `dashboard` | `tableau_de_bord` |

`Household` → `Foyer`, `Membership` → `Adhesion`, `HouseholdScopedManager` → `GestionnaireDeFoyer`,
`/health/` → `/sante/`, `manage.py healthcheck` → `manage.py verifier_sante`.

## Ce qui reste en anglais, et pourquoi

- Les noms de fichiers que Django découvre ou attend par convention : `models.py`, `views.py`,
  `forms.py`, `urls.py`, `admin.py`, `apps.py`, `middleware.py`, `migrations/`, `management/commands/`.
- Les champs hérités de Django sur l'utilisateur (`first_name`, `is_active`, `password`…) et les
  méthodes du framework que l'on surcharge (`get_queryset`, `form_valid`, `dispatch`…).
- Les variables d'environnement standard de l'écosystème (`SECRET_KEY`, `DEBUG`, `DATABASE_URL`,
  `ALLOWED_HOSTS`, `EMAIL_URL`). Celles propres à l'application sont en français
  (`INSCRIPTION_OUVERTE`, `DERRIERE_PROXY`, `HTTPS_OBLIGATOIRE`).
