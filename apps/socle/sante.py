from django.db import DEFAULT_DB_ALIAS, connections
from django.db.migrations.executor import MigrationExecutor


def base_joignable() -> bool:
    try:
        with connections[DEFAULT_DB_ALIAS].cursor() as curseur:
            curseur.execute("SELECT 1")
    except Exception:
        return False
    return True


def migrations_en_attente() -> list[str]:
    executeur = MigrationExecutor(connections[DEFAULT_DB_ALIAS])
    plan = executeur.migration_plan(executeur.loader.graph.leaf_nodes())
    return [f"{migration.app_label}.{migration.name}" for migration, _ in plan]
