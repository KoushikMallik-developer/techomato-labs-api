"""
Django settings for Techomato Labs API.

Everything that differs between environments is read from environment
variables (see `.env.example`), so the same image runs in dev and prod.
"""
import os
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------
# env helpers
# --------------------------------------------------------------------------
def env(name, default=None):
    value = os.environ.get(name)
    return default if value is None or value == '' else value


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None or value == '':
        return default
    return value.strip().lower() in ('1', 'true', 'yes', 'on')


def env_int(name, default):
    value = os.environ.get(name)
    if value is None or value == '':
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ImproperlyConfigured(f'{name} must be an integer, got {value!r}') from exc


def env_list(name, default=''):
    raw = os.environ.get(name)
    if raw is None:
        raw = default
    return [item.strip() for item in raw.split(',') if item.strip()]


# --------------------------------------------------------------------------
# core
# --------------------------------------------------------------------------
DEBUG = env_bool('DJANGO_DEBUG', False)

SECRET_KEY = env('DJANGO_SECRET_KEY')
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured('DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is off.')
    SECRET_KEY = 'insecure-dev-only-key-do-not-use-in-production'

# URL prefix of Django's built-in admin (data browser). Use something unguessable in production.
DJANGO_ADMIN_URL = (env('DJANGO_ADMIN_URL', 'django-admin').strip('/') or 'django-admin') + '/'

ALLOWED_HOSTS = env_list('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1')
# Render exposes the service's public *.onrender.com hostname through this variable.
_render_host = env('RENDER_EXTERNAL_HOSTNAME')
if _render_host and _render_host not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(_render_host)

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'corsheaders',
    'rest_framework',
    'apps.core',
    'apps.accounts',
    'apps.projects',
    'apps.community',
    'apps.moderation',
]

MIDDLEWARE = [
    'apps.core.middleware.HealthCheckMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'
WSGI_APPLICATION = 'config.wsgi.application'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

# Superseded by our own deploy check techomato.E002 (minimum length + character variety).
SILENCED_SYSTEM_CHECKS = ['security.W009']

AUTH_USER_MODEL = 'accounts.User'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = False
USE_TZ = True


# --------------------------------------------------------------------------
# database (PostgreSQL)
# --------------------------------------------------------------------------
def database_from_url(url):
    """Parse postgres://user:pass@host:port/dbname?sslmode=require into a Django DATABASES entry."""
    parts = urlsplit(url)
    if parts.scheme not in ('postgres', 'postgresql'):
        raise ImproperlyConfigured('DATABASE_URL must start with postgres:// or postgresql://')
    if not parts.hostname or not parts.path.strip('/'):
        raise ImproperlyConfigured('DATABASE_URL needs a host and a database name.')
    config = {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': unquote(parts.path.lstrip('/')),
        'USER': unquote(parts.username or ''),
        'PASSWORD': unquote(parts.password or ''),
        'HOST': parts.hostname,
        'PORT': str(parts.port or 5432),
        'CONN_MAX_AGE': env_int('DB_CONN_MAX_AGE', 60),
        'CONN_HEALTH_CHECKS': True,
    }
    sslmode = parse_qs(parts.query).get('sslmode', [''])[0]
    if sslmode:
        config['OPTIONS'] = {'sslmode': sslmode}
    return config


# DATABASE_URL (Render and most PaaS) wins over the individual POSTGRES_* variables.
# `sqlite` exists only so the unit tests can run without a Postgres server.
DATABASE_ENGINE = env('DATABASE_ENGINE', 'postgresql').lower()
if env('DATABASE_URL'):
    DATABASES = {'default': database_from_url(env('DATABASE_URL'))}
elif DATABASE_ENGINE == 'sqlite':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': env('SQLITE_PATH', str(BASE_DIR / 'db.sqlite3')),
        }
    }
elif DATABASE_ENGINE == 'postgresql':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': env('POSTGRES_DB', 'techomato'),
            'USER': env('POSTGRES_USER', 'techomato'),
            'PASSWORD': env('POSTGRES_PASSWORD', ''),
            'HOST': env('POSTGRES_HOST', 'localhost'),
            'PORT': env('POSTGRES_PORT', '5432'),
            'CONN_MAX_AGE': env_int('DB_CONN_MAX_AGE', 60),
            'CONN_HEALTH_CHECKS': True,
        }
    }
else:
    raise ImproperlyConfigured("DATABASE_ENGINE must be 'postgresql' or 'sqlite'.")


# --------------------------------------------------------------------------
# Redis: cache, sessions, Celery broker (separate logical databases)
# --------------------------------------------------------------------------
# Cache, sessions and the Celery broker use different key prefixes/names, so they can
# share one logical database (set every *_DB to 0) on hosts without multi-DB Redis.
REDIS_URL = env('REDIS_URL', 'redis://localhost:6379').rstrip('/')
REDIS_CACHE_DB = env_int('REDIS_CACHE_DB', 0)
REDIS_SESSION_DB = env_int('REDIS_SESSION_DB', 1)
REDIS_BROKER_DB = env_int('REDIS_BROKER_DB', 2)
REDIS_RESULT_DB = env_int('REDIS_RESULT_DB', 3)

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': f'{REDIS_URL}/{REDIS_CACHE_DB}',
        'KEY_PREFIX': 'techomato',
    },
    'sessions': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': f'{REDIS_URL}/{REDIS_SESSION_DB}',
        'KEY_PREFIX': 'techomato-session',
    },
}

SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
SESSION_CACHE_ALIAS = 'sessions'
SESSION_COOKIE_NAME = env('SESSION_COOKIE_NAME', 'techomato_sessionid')
SESSION_COOKIE_AGE = env_int('SESSION_COOKIE_AGE', 60 * 60 * 24 * 14)
SESSION_COOKIE_HTTPONLY = True


# --------------------------------------------------------------------------
# cookies / CSRF / CORS (the SPA lives on another origin)
# --------------------------------------------------------------------------
FRONTEND_URL = env('FRONTEND_URL', 'http://localhost:5173').rstrip('/')
_default_origins = FRONTEND_URL + ',http://127.0.0.1:5173'
CORS_ALLOWED_ORIGINS = env_list('CORS_ALLOWED_ORIGINS', _default_origins)
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = env_list('CSRF_TRUSTED_ORIGINS', ','.join(CORS_ALLOWED_ORIGINS))

# Cross-site deployments (SPA and API on different registrable domains) need
# SAMESITE=None together with SECURE=true.
SESSION_COOKIE_SAMESITE = env('SESSION_COOKIE_SAMESITE', 'Lax')
CSRF_COOKIE_SAMESITE = env('CSRF_COOKIE_SAMESITE', SESSION_COOKIE_SAMESITE)
SESSION_COOKIE_SECURE = env_bool('SESSION_COOKIE_SECURE', not DEBUG)
CSRF_COOKIE_SECURE = env_bool('CSRF_COOKIE_SECURE', not DEBUG)

if env_bool('USE_X_FORWARDED_PROTO', False):
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = env_bool('SECURE_SSL_REDIRECT', False)
SECURE_HSTS_SECONDS = env_int('SECURE_HSTS_SECONDS', 0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool('SECURE_HSTS_INCLUDE_SUBDOMAINS', False)
SECURE_HSTS_PRELOAD = env_bool('SECURE_HSTS_PRELOAD', False)


# --------------------------------------------------------------------------
# passwords
# --------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {'min_length': env_int('PASSWORD_MIN_LENGTH', 8)},
    },
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

PASSWORD_RESET_TIMEOUT = env_int('PASSWORD_RESET_TIMEOUT', 60 * 30)
EMAIL_VERIFICATION_MAX_AGE = env_int('EMAIL_VERIFICATION_MAX_AGE', 60 * 60 * 24 * 3)


# --------------------------------------------------------------------------
# REST framework
# --------------------------------------------------------------------------
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': ['apps.core.authentication.ApiSessionAuthentication'],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticated'],
    'DEFAULT_RENDERER_CLASSES': ['rest_framework.renderers.JSONRenderer'],
    'DEFAULT_PARSER_CLASSES': ['apps.core.parsers.SafeJSONParser'],
    'EXCEPTION_HANDLER': 'apps.core.exceptions.api_exception_handler',
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': env('THROTTLE_ANON', '300/min'),
        'user': env('THROTTLE_USER', '600/min'),
        'auth': env('THROTTLE_AUTH', '20/min'),
    },
    # Number of trusted reverse proxies in front of the API (used to find the
    # real client IP for throttling). 0 = use REMOTE_ADDR.
    'NUM_PROXIES': env_int('THROTTLE_NUM_PROXIES', 0),
}


# --------------------------------------------------------------------------
# static files (Django admin only)
# --------------------------------------------------------------------------
STATIC_URL = '/static/'
STATIC_ROOT = env('STATIC_ROOT', str(BASE_DIR / 'staticfiles'))
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}


# --------------------------------------------------------------------------
# email
# --------------------------------------------------------------------------
EMAIL_BACKEND = env('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = env('EMAIL_HOST', 'localhost')
EMAIL_PORT = env_int('EMAIL_PORT', 25)
EMAIL_HOST_USER = env('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = env_bool('EMAIL_USE_TLS', False)
EMAIL_USE_SSL = env_bool('EMAIL_USE_SSL', False)
EMAIL_TIMEOUT = env_int('EMAIL_TIMEOUT', 10)
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', 'Techomato Labs <no-reply@techomato.dev>')


# --------------------------------------------------------------------------
# Celery
# --------------------------------------------------------------------------
CELERY_BROKER_URL = env('CELERY_BROKER_URL', f'{REDIS_URL}/{REDIS_BROKER_DB}')
CELERY_RESULT_BACKEND = env('CELERY_RESULT_BACKEND', f'{REDIS_URL}/{REDIS_RESULT_DB}')
CELERY_TASK_ALWAYS_EAGER = env_bool('CELERY_TASK_ALWAYS_EAGER', False)
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_TIME_LIMIT = env_int('CELERY_TASK_TIME_LIMIT', 60)
CELERY_RESULT_EXPIRES = 60 * 60
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TIMEZONE = TIME_ZONE


# --------------------------------------------------------------------------
# OAuth (leave blank to disable a provider)
# --------------------------------------------------------------------------
OAUTH_PROVIDERS = {
    'google': {
        'client_id': env('GOOGLE_CLIENT_ID', ''),
        'client_secret': env('GOOGLE_CLIENT_SECRET', ''),
    },
    'github': {
        'client_id': env('GITHUB_CLIENT_ID', ''),
        'client_secret': env('GITHUB_CLIENT_SECRET', ''),
    },
}
OAUTH_HTTP_TIMEOUT = env_int('OAUTH_HTTP_TIMEOUT', 10)


# --------------------------------------------------------------------------
# admin bootstrap (used by `manage.py ensure_admin`)
# --------------------------------------------------------------------------
ADMIN_EMAIL = env('ADMIN_EMAIL', '')
ADMIN_PASSWORD = env('ADMIN_PASSWORD', '')
ADMIN_NAME = env('ADMIN_NAME', 'Techomato Admin')


# --------------------------------------------------------------------------
# logging
# --------------------------------------------------------------------------
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'default': {'format': '%(asctime)s %(levelname)s %(name)s: %(message)s'},
    },
    'handlers': {
        'console': {'class': 'logging.StreamHandler', 'formatter': 'default'},
    },
    'root': {'handlers': ['console'], 'level': env('LOG_LEVEL', 'INFO')},
}
