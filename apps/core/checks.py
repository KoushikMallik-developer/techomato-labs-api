"""
Deployment checks (`manage.py check --deploy`).

The container start-up script runs these whenever DJANGO_DEBUG is off and
refuses to boot on an *error*, so a production deploy can't silently run with
development defaults (placeholder secret key, well-known admin password,
plain-HTTP origins, insecure cookies, ...).
"""
from django.conf import settings
from django.core.checks import Error, Tags, Warning, register

KNOWN_WEAK_PASSWORDS = {
    'circuitadmin!1',
    'admin',
    'password',
    'techomato_dev_password',
    'change-me-admin-password',
    'changeme',
}
# 32+ chars of mixed random characters is >= 190 bits; Render's generated values are 44 chars.
MIN_SECRET_LENGTH = 32
MIN_SECRET_UNIQUE_CHARS = 12
PLACEHOLDER_MARKERS = ('change-me', 'changeme', 'insecure', 'replace-me', 'example')


def _looks_like_placeholder(value):
    lowered = (value or '').lower()
    return any(marker in lowered for marker in PLACEHOLDER_MARKERS)


def _https(url):
    return url.lower().startswith('https://')


@register(Tags.security, deploy=True)
def production_configuration(app_configs, **kwargs):
    problems = []

    def error(msg, code, hint=None):
        problems.append(Error(msg, hint=hint, id=f'techomato.E{code}'))

    def warn(msg, code, hint=None):
        problems.append(Warning(msg, hint=hint, id=f'techomato.W{code}'))

    if settings.DEBUG:
        error('DJANGO_DEBUG is on.', '001', 'Set DJANGO_DEBUG=false; debug pages leak code, settings and request data.')

    key = settings.SECRET_KEY
    if len(key) < MIN_SECRET_LENGTH or len(set(key)) < MIN_SECRET_UNIQUE_CHARS or _looks_like_placeholder(key):
        error(
            'DJANGO_SECRET_KEY is short, low-variety or a placeholder.',
            '002',
            'Use 32+ random characters, e.g. python -c "import secrets; print(secrets.token_urlsafe(64))"',
        )

    if settings.ADMIN_EMAIL and settings.ADMIN_PASSWORD:
        pw = settings.ADMIN_PASSWORD
        if len(pw) < 12 or pw.lower() in KNOWN_WEAK_PASSWORDS or _looks_like_placeholder(pw):
            error('ADMIN_PASSWORD is weak, short (<12) or a well-known default.', '003', 'Use a long random password.')

    db = settings.DATABASES['default']
    if 'postgresql' in db['ENGINE']:
        password = db.get('PASSWORD') or ''
        if len(password) < 12 or password.lower() in KNOWN_WEAK_PASSWORDS or _looks_like_placeholder(password):
            error('POSTGRES_PASSWORD is weak, short (<12) or a placeholder.', '004', 'Use a long random password.')

    if not _https(settings.FRONTEND_URL):
        error('FRONTEND_URL is not https://.', '005', 'Email links and CORS must point at the HTTPS site.')
    for origin in list(settings.CORS_ALLOWED_ORIGINS) + list(settings.CSRF_TRUSTED_ORIGINS):
        if not _https(origin):
            error(f'Origin {origin!r} is not https://.', '005', 'Use HTTPS origins in production (no localhost).')
            break

    if not settings.SESSION_COOKIE_SECURE or not settings.CSRF_COOKIE_SECURE:
        error('Session/CSRF cookies are not marked Secure.', '006', 'Set SESSION_COOKIE_SECURE and CSRF_COOKIE_SECURE=true.')

    if '*' in settings.ALLOWED_HOSTS:
        error('DJANGO_ALLOWED_HOSTS contains "*".', '007', 'List the exact API hostnames.')
    elif set(settings.ALLOWED_HOSTS) <= {'localhost', '127.0.0.1', '[::1]'}:
        error('DJANGO_ALLOWED_HOSTS only lists localhost.', '007', 'Add your API domain, e.g. api.techomato.com.')

    if settings.EMAIL_BACKEND.endswith(('console.EmailBackend', 'locmem.EmailBackend', 'dummy.EmailBackend')):
        warn('EMAIL_BACKEND does not deliver real email.', '001', 'Users will not receive verification/reset emails.')

    if not settings.SECURE_HSTS_SECONDS:
        warn('HSTS is disabled.', '002', 'Set SECURE_HSTS_SECONDS (e.g. 31536000) once HTTPS works everywhere.')

    if settings.REST_FRAMEWORK.get('NUM_PROXIES') == 0:
        warn(
            'THROTTLE_NUM_PROXIES is 0.',
            '003',
            'Behind a reverse proxy set it to the number of proxies, or every client shares one rate-limit bucket.',
        )

    if not settings.SECURE_PROXY_SSL_HEADER and not settings.SECURE_SSL_REDIRECT:
        warn('USE_X_FORWARDED_PROTO is off.', '004', 'Turn it on when a TLS-terminating proxy sits in front.')

    return problems
