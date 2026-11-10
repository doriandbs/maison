from pathlib import Path

import environ

RACINE = Path(__file__).resolve().parent.parent

env = environ.Env()
environ.Env.read_env(RACINE / ".env")

DEBUG = env.bool("DEBUG", default=False)
SECRET_KEY = env("SECRET_KEY")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

INSCRIPTION_OUVERTE = env.bool("INSCRIPTION_OUVERTE", default=True)
DERRIERE_PROXY = env.bool("DERRIERE_PROXY", default=False)
HTTPS_OBLIGATOIRE = env.bool("HTTPS_OBLIGATOIRE", default=not DEBUG)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "axes",
    "apps.socle",
    "apps.utilisateurs",
    "apps.foyers",
    "apps.banque",
    "apps.budget",
    "apps.documents",
    "apps.tableau_de_bord",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.foyers.middleware.IntergicielFoyerCourant",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_ratelimit.middleware.RatelimitMiddleware",
    "axes.middleware.AxesMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [RACINE / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.foyers.contexte.foyer_courant",
                "apps.socle.navigation.navigation",
            ],
        },
    },
]

DATABASES = {"default": env.db("DATABASE_URL")}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Cache en base : partagé entre les workers gunicorn sans Redis (limitation de débit).
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "cache",
    }
}

# --- Authentification ---
AUTH_USER_MODEL = "utilisateurs.Utilisateur"
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LOGIN_URL = "utilisateurs:connexion"
LOGIN_REDIRECT_URL = "accueil"
LOGOUT_REDIRECT_URL = "utilisateurs:connexion"

# Verrouillage après échecs de connexion répétés (couple e-mail + adresse IP).
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 0.25  # heures
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
# Sans cela axes cherche un champ « email » (notre USERNAME_FIELD), absent du
# formulaire de connexion Django : les échecs ne seraient rattachés à aucun compte.
AXES_USERNAME_FORM_FIELD = "username"
AXES_LOCKOUT_TEMPLATE = "socle/trop_de_requetes.html"

RATELIMIT_VIEW = "apps.socle.views.trop_de_requetes"
if DERRIERE_PROXY:
    RATELIMIT_IP_META_KEY = "apps.socle.reseau.ip_cliente"
else:
    AXES_IPWARE_META_PRECEDENCE_ORDER = ["REMOTE_ADDR"]

# --- Internationalisation ---
LANGUAGE_CODE = "fr"
TIME_ZONE = "Europe/Paris"
USE_I18N = True
USE_TZ = True

# --- Fichiers statiques ---
STATIC_URL = "static/"
STATIC_ROOT = RACINE / "staticfiles"
STATICFILES_DIRS = [RACINE / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}

# --- Fichiers déposés ---
# Hors des fichiers statiques et sans MEDIA_URL : ils ne sont servis que par une vue
# qui vérifie les droits (voir apps.documents.views.VueFichierDocument).
MEDIA_ROOT = env.path("MEDIA_ROOT", default=RACINE / "media")
TAILLE_MAX_DOCUMENT = env.int("TAILLE_MAX_DOCUMENT_MO", default=10) * 1024 * 1024
# Au-delà de 2,5 Mo, Django passe par un fichier temporaire plutôt que la mémoire.
DATA_UPLOAD_MAX_MEMORY_SIZE = 2_621_440

# --- E-mail ---
# Deux façons de configurer l'envoi : variables séparées (EMAIL_HOST…), prioritaires,
# ou une seule EMAIL_URL. Sans rien, les e-mails s'affichent dans la console.
if env("EMAIL_HOST", default=""):
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = env("EMAIL_HOST")
    EMAIL_PORT = env.int("EMAIL_PORT", default=587)
    EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
    EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
    EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
    EMAIL_USE_SSL = env.bool("EMAIL_USE_SSL", default=False)
else:
    vars().update(env.email_url("EMAIL_URL", default="consolemail://"))
# Un serveur SMTP qui ne répond pas ne doit pas bloquer un processus gunicorn.
EMAIL_TIMEOUT = 10
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Maison <maison@localhost>")

# --- Sécurité transport ---
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
if HTTPS_OBLIGATOIRE:
    SECURE_SSL_REDIRECT = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_REDIRECT_EXEMPT = [r"^sante/$"]

# Inscrire le domaine dans la liste « preload » des navigateurs est quasi irréversible :
# c'est un choix à faire à la main, pas un réglage par défaut.
SILENCED_SYSTEM_CHECKS = ["security.W021"]
