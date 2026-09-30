"""
Settings used by the test suite: the real settings, minus everything that
needs Redis/SMTP/a broker, so tests are fast and hermetic.

The database still comes from the environment (PostgreSQL in Docker;
set DATABASE_ENGINE=sqlite to run without a server).
"""
import os

os.environ.setdefault('DJANGO_SECRET_KEY', 'test-secret-key')
os.environ.setdefault('DJANGO_DEBUG', 'false')

from .settings import *  # noqa: E402,F401,F403
from .settings import MIDDLEWARE, REST_FRAMEWORK  # noqa: E402

DEBUG = False
ALLOWED_HOSTS = ['testserver', 'localhost']

CACHES = {
    'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'default'},
    'sessions': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'sessions'},
}

MIDDLEWARE = [m for m in MIDDLEWARE if 'whitenoise' not in m]
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False

STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}

REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    'DEFAULT_THROTTLE_RATES': {'anon': '10000/min', 'user': '10000/min', 'auth': '10000/min'},
}

FRONTEND_URL = 'http://frontend.test'
DEFAULT_FROM_EMAIL = 'Techomato Labs <no-reply@techomato.dev>'
PASSWORD_RESET_TIMEOUT = 1800
EMAIL_VERIFICATION_MAX_AGE = 259200
ADMIN_EMAIL = ''
ADMIN_PASSWORD = ''
OAUTH_PROVIDERS = {
    'google': {'client_id': 'g-id', 'client_secret': 'g-secret'},
    'github': {'client_id': 'gh-id', 'client_secret': 'gh-secret'},
}
