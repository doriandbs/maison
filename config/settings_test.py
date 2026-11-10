import os

os.environ.setdefault("SECRET_KEY", "cle-de-test-non-secrete")
os.environ.setdefault("DEBUG", "False")

from .settings import *  # noqa: E402, F403

# La base de test est toujours créée en UTF-8, même si le modèle par défaut du
# serveur PostgreSQL est dans un autre encodage (WIN1252 sur une installation Windows).
DATABASES["default"]["TEST"] = {"CHARSET": "UTF8", "TEMPLATE": "template0"}  # noqa: F405

HTTPS_OBLIGATOIRE = False
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# Désactivés par défaut ; les tests qui les vérifient les réactivent explicitement.
AXES_ENABLED = False
RATELIMIT_ENABLE = False
