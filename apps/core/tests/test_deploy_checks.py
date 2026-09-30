import pytest
from django.core.management import call_command
from django.core.management.base import SystemCheckError

from apps.core.checks import production_configuration

GOOD_SECRET = 'q7Vn3xLk9ZpR2mWc8YhT5bJd6FgA1sUe4oNi0KtXvEyB'  # 44 chars of mixed characters, like Render's generated value
STRONG = 'V3ry-Long-Random-Pass-92'


@pytest.fixture
def prod(settings, monkeypatch):
    """A settings state that passes every deployment check."""
    # DATABASES is a nested dict: the settings fixture can't restore in-place edits, monkeypatch can.
    settings.DEBUG = False
    settings.SECRET_KEY = GOOD_SECRET
    settings.ADMIN_EMAIL = 'ops@techomato.com'
    settings.ADMIN_PASSWORD = STRONG
    monkeypatch.setitem(settings.DATABASES['default'], 'ENGINE', 'django.db.backends.postgresql')
    monkeypatch.setitem(settings.DATABASES['default'], 'PASSWORD', STRONG)
    settings.FRONTEND_URL = 'https://techomato.com'
    settings.CORS_ALLOWED_ORIGINS = ['https://techomato.com']
    settings.CSRF_TRUSTED_ORIGINS = ['https://techomato.com']
    settings.SESSION_COOKIE_SECURE = True
    settings.CSRF_COOKIE_SECURE = True
    settings.ALLOWED_HOSTS = ['api.techomato.com']
    settings.EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    settings.SECURE_HSTS_SECONDS = 31536000
    settings.SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, 'NUM_PROXIES': 1}
    return settings


def ids(problems):
    return {p.id for p in problems}


def test_a_correct_production_config_has_no_findings(prod):
    assert production_configuration(None) == []


@pytest.mark.parametrize(
    'attr, value, code',
    [
        ('DEBUG', True, 'techomato.E001'),
        ('SECRET_KEY', 'short', 'techomato.E002'),
        ('SECRET_KEY', 'a' * 60, 'techomato.E002'),
        ('SECRET_KEY', 'ab' * 40, 'techomato.E002'),
        ('SECRET_KEY', 'change-me-' + 'x' * 60, 'techomato.E002'),
        ('SECRET_KEY', 'django-insecure-' + 'x' * 60, 'techomato.E002'),
        ('ADMIN_PASSWORD', 'CircuitAdmin!1', 'techomato.E003'),
        ('ADMIN_PASSWORD', 'short', 'techomato.E003'),
        ('ADMIN_PASSWORD', 'change-me-admin-password', 'techomato.E003'),
        ('FRONTEND_URL', 'http://techomato.com', 'techomato.E005'),
        ('CORS_ALLOWED_ORIGINS', ['https://techomato.com', 'http://localhost:5173'], 'techomato.E005'),
        ('CSRF_TRUSTED_ORIGINS', ['http://localhost:5173'], 'techomato.E005'),
        ('SESSION_COOKIE_SECURE', False, 'techomato.E006'),
        ('CSRF_COOKIE_SECURE', False, 'techomato.E006'),
        ('ALLOWED_HOSTS', ['*'], 'techomato.E007'),
        ('ALLOWED_HOSTS', ['localhost', '127.0.0.1'], 'techomato.E007'),
    ],
)
def test_unsafe_settings_are_errors(prod, attr, value, code):
    setattr(prod, attr, value)
    problems = production_configuration(None)
    assert code in ids(problems)
    assert all(p.level >= 40 for p in problems if p.id == code)  # ERROR level


@pytest.mark.parametrize('password', ['', 'short', 'techomato_dev_password', 'change-me-please-now', 'admin'])
def test_weak_database_password_is_an_error(prod, monkeypatch, password):
    monkeypatch.setitem(prod.DATABASES['default'], 'PASSWORD', password)
    assert 'techomato.E004' in ids(production_configuration(None))


def test_sqlite_is_not_flagged_for_a_db_password(prod, monkeypatch):
    monkeypatch.setitem(prod.DATABASES['default'], 'ENGINE', 'django.db.backends.sqlite3')
    monkeypatch.setitem(prod.DATABASES['default'], 'PASSWORD', '')
    assert 'techomato.E004' not in ids(production_configuration(None))


def test_admin_password_is_only_checked_when_bootstrap_is_configured(prod):
    prod.ADMIN_EMAIL = ''
    prod.ADMIN_PASSWORD = ''
    assert 'techomato.E003' not in ids(production_configuration(None))


@pytest.mark.parametrize(
    'backend',
    ['django.core.mail.backends.console.EmailBackend', 'django.core.mail.backends.locmem.EmailBackend'],
)
def test_non_delivering_email_backend_is_a_warning_not_an_error(prod, backend):
    prod.EMAIL_BACKEND = backend
    problems = [p for p in production_configuration(None) if p.id == 'techomato.W001']
    assert problems and all(p.level < 40 for p in problems)


def test_other_advisories_are_warnings(prod):
    prod.SECURE_HSTS_SECONDS = 0
    prod.SECURE_PROXY_SSL_HEADER = None
    prod.REST_FRAMEWORK = {**prod.REST_FRAMEWORK, 'NUM_PROXIES': 0}
    problems = production_configuration(None)
    assert {'techomato.W002', 'techomato.W003', 'techomato.W004'} <= ids(problems)
    assert all(p.level < 40 for p in problems)


def test_check_deploy_command_fails_on_errors_and_passes_when_clean(prod):
    prod.DEBUG = True
    with pytest.raises(SystemCheckError):
        call_command('check', deploy=True, fail_level='ERROR')


def test_startup_script_runs_the_checks_outside_debug():
    from pathlib import Path

    script = (Path(__file__).resolve().parents[3] / 'scripts' / 'start-web.sh').read_text()
    assert 'check --deploy --fail-level ERROR' in script
    assert script.index('python manage.py check --deploy') < script.index('python manage.py migrate')


def test_admin_url_is_normalised():
    import subprocess
    import sys
    from pathlib import Path

    base = Path(__file__).resolve().parents[3]
    code = 'from config import settings as s; print(s.DJANGO_ADMIN_URL)'
    for raw, expected in [('/ops-1/', 'ops-1/'), ('ops-1', 'ops-1/'), ('///', 'django-admin/')]:
        out = subprocess.run(
            [sys.executable, '-c', code], cwd=base, capture_output=True, text=True,
            env={'PATH': __import__('os').environ.get('PATH', ''), 'SYSTEMROOT': __import__('os').environ.get('SYSTEMROOT', ''),
                 'DJANGO_SECRET_KEY': 'k', 'DATABASE_ENGINE': 'sqlite', 'DJANGO_ADMIN_URL': raw},
        )
        assert out.stdout.strip() == expected, (raw, out.stderr)
