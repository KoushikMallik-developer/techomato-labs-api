import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest
from django.test import RequestFactory
from rest_framework import exceptions
from rest_framework.test import APIClient

from apps.core import exceptions as core_exceptions
from apps.core import views as core_views
from apps.core.sessions import ADMIN_SESSION_KEY, keep_admin_session
from apps.core.timefields import EpochMillisField, to_millis
from config import settings as project_settings

BASE_DIR = Path(project_settings.BASE_DIR)


# ---------------------------------------------------------------- exceptions
class TestErrorFormat:
    def test_first_message_search(self):
        first = core_exceptions._first_message
        assert first('plain') == 'plain'
        assert first({'a': ['deep message']}) == 'deep message'
        assert first([{'a': ['x']}]) == 'x'
        assert first({}) is None
        assert first([]) is None
        assert first(42) is None
        assert first({'a': [], 'b': 'later'}) == 'later'

    def test_error_response(self):
        response = core_exceptions.error_response('nope', 418, 'teapot')
        assert response.status_code == 418
        assert response.data == {'detail': 'nope', 'code': 'teapot'}

    def test_unhandled_exceptions_are_left_to_django(self):
        assert core_exceptions.api_exception_handler(RuntimeError('x'), {}) is None

    def test_validation_error_without_message_still_has_a_detail(self):
        response = core_exceptions.api_exception_handler(exceptions.ValidationError({}), {})
        assert response.data['detail'] == 'Invalid request.'
        assert response.data['code'] == 'validation_error'

    def test_list_style_validation_error(self):
        response = core_exceptions.api_exception_handler(exceptions.ValidationError(['broken']), {})
        assert response.data['detail'] == 'broken'
        assert 'errors' not in response.data

    def test_throttled_reports_retry_after(self):
        response = core_exceptions.api_exception_handler(exceptions.Throttled(wait=12.4), {})
        assert response.status_code == 429
        assert response.data['retryAfter'] == 13  # rounded up, never down
        assert response.data['code'] == 'throttled'

    def test_permission_and_not_found_shapes(self, client, auth_client):
        assert client.get('/api/v1/auth/me/').json()['code'] == 'not_authenticated'
        assert auth_client.get('/api/v1/projects/00000000-0000-0000-0000-000000000000/').json() == {
            'detail': 'No Project matches the given query.',
            'code': 'not_found',
        }

    def test_method_not_allowed_shape(self, auth_client):
        response = auth_client.put('/api/v1/projects/', {}, format='json')
        assert response.status_code == 405
        assert response.json()['code'] == 'method_not_allowed'


# --------------------------------------------------------------- health / 500
class TestHealthAndServerError:
    def test_database_down_is_reported(self, client):
        broken = mock.Mock()
        broken.cursor.side_effect = RuntimeError('db down')
        with mock.patch.object(core_views, 'connection', broken):
            response = client.get('/api/v1/health/')
        assert response.status_code == 503
        assert response.json() == {'status': 'error', 'database': 'error', 'cache': 'ok'}

    def test_health_is_public_and_read_only(self, client):
        assert client.post('/api/v1/health/').status_code == 405

    def test_server_error_handler_is_json_for_the_api(self):
        response = core_views.server_error(RequestFactory().get('/api/v1/anything/'))
        assert response.status_code == 500
        assert json.loads(response.content) == {'detail': 'Something went wrong on our side.', 'code': 'server_error'}

    def test_server_error_handler_is_default_elsewhere(self):
        response = core_views.server_error(RequestFactory().get('/elsewhere/'))
        assert response.status_code == 500
        assert response['Content-Type'].startswith('text/html')

    def test_not_found_handler_direct(self):
        response = core_views.not_found(RequestFactory().get('/api/v1/x/'), Exception())
        assert response.status_code == 404
        assert json.loads(response.content)['code'] == 'not_found'


# ------------------------------------------------------------- time fields
class TestTimeFields:
    def test_to_millis(self):
        from datetime import datetime, timezone

        moment = datetime(2026, 1, 2, 3, 4, 5, 678000, tzinfo=timezone.utc)
        assert to_millis(moment) == 1767323045678
        assert to_millis(None) is None

    def test_field_is_read_only_and_returns_int(self):
        from datetime import datetime, timezone

        field = EpochMillisField()
        assert field.read_only
        assert field.to_representation(datetime(2026, 1, 1, tzinfo=timezone.utc)) == 1767225600000

    def test_api_timestamps_are_integers_and_consistent(self, auth_client):
        created = auth_client.post('/api/v1/projects/', {'name': 'T'}, format='json').json()
        assert isinstance(created['createdAt'], int)
        assert created['updatedAt'] >= created['createdAt']
        assert created['publishedAt'] is None and created['approvedAt'] is None


# ---------------------------------------------------------------- sessions
class TestAdminSessionHelper:
    def test_restores_admin_key_after_flush(self):
        request = mock.Mock()
        request.session = {ADMIN_SESSION_KEY: 'abc'}
        with keep_admin_session(request):
            request.session.clear()
        assert request.session[ADMIN_SESSION_KEY] == 'abc'

    def test_does_nothing_without_admin_key(self):
        request = mock.Mock()
        request.session = {}
        with keep_admin_session(request):
            pass
        assert request.session == {}

    def test_restores_even_if_the_block_raises(self):
        request = mock.Mock()
        request.session = {ADMIN_SESSION_KEY: 'abc'}
        with pytest.raises(RuntimeError):
            with keep_admin_session(request):
                request.session.clear()
                raise RuntimeError('boom')
        assert request.session[ADMIN_SESSION_KEY] == 'abc'

    def test_garbage_admin_session_value_is_treated_as_signed_out(self, settings):
        api = APIClient()
        session = api.session
        session[ADMIN_SESSION_KEY] = 'not-a-uuid'
        session.save()
        api.cookies[settings.SESSION_COOKIE_NAME] = session.session_key
        assert api.get('/api/v1/admin/session/').json() == {'isAdmin': False, 'email': None}
        assert api.get('/api/v1/admin/circuits/pending/').status_code == 401

    def test_admin_session_for_unknown_user_is_signed_out(self, settings):
        api = APIClient()
        session = api.session
        session[ADMIN_SESSION_KEY] = '00000000-0000-0000-0000-000000000000'
        session.save()
        api.cookies[settings.SESSION_COOKIE_NAME] = session.session_key
        assert api.get('/api/v1/admin/session/').json()['isAdmin'] is False

    def test_session_cookie_is_httponly_and_named_from_settings(self, client, user, settings):
        response = client.post('/api/v1/auth/login/', {'email': user.email, 'password': 'correct-horse-9'}, format='json')
        morsel = response.cookies[settings.SESSION_COOKIE_NAME]
        assert morsel['httponly']
        assert morsel['samesite'] == settings.SESSION_COOKIE_SAMESITE


# ---------------------------------------------------------------- env helpers
class TestEnvHelpers:
    def test_env_treats_blank_as_unset(self, monkeypatch):
        monkeypatch.setenv('X_TEST', '')
        assert project_settings.env('X_TEST', 'fallback') == 'fallback'
        monkeypatch.setenv('X_TEST', 'value')
        assert project_settings.env('X_TEST', 'fallback') == 'value'
        monkeypatch.delenv('X_TEST')
        assert project_settings.env('X_TEST') is None

    @pytest.mark.parametrize('raw, expected', [
        ('true', True), ('TRUE', True), ('1', True), ('yes', True), ('on', True), (' True ', True),
        ('false', False), ('0', False), ('no', False), ('off', False), ('nonsense', False),
    ])
    def test_env_bool(self, monkeypatch, raw, expected):
        monkeypatch.setenv('X_BOOL', raw)
        assert project_settings.env_bool('X_BOOL', not expected) is expected

    def test_env_bool_default_when_unset_or_blank(self, monkeypatch):
        monkeypatch.delenv('X_BOOL', raising=False)
        assert project_settings.env_bool('X_BOOL', True) is True
        monkeypatch.setenv('X_BOOL', '')
        assert project_settings.env_bool('X_BOOL', True) is True

    def test_env_int(self, monkeypatch):
        monkeypatch.setenv('X_INT', '42')
        assert project_settings.env_int('X_INT', 1) == 42
        monkeypatch.delenv('X_INT')
        assert project_settings.env_int('X_INT', 7) == 7

    def test_env_int_rejects_garbage_with_a_helpful_message(self, monkeypatch):
        from django.core.exceptions import ImproperlyConfigured

        monkeypatch.setenv('X_INT', 'twelve')
        with pytest.raises(ImproperlyConfigured, match='X_INT'):
            project_settings.env_int('X_INT', 1)

    def test_env_list(self, monkeypatch):
        monkeypatch.setenv('X_LIST', ' a, b ,,c ')
        assert project_settings.env_list('X_LIST') == ['a', 'b', 'c']
        monkeypatch.setenv('X_LIST', '')
        assert project_settings.env_list('X_LIST', 'x,y') == []
        monkeypatch.delenv('X_LIST')
        assert project_settings.env_list('X_LIST', 'x,y') == ['x', 'y']


# ------------------------------------------------- settings in a fresh process
def load_settings(**overrides):
    """Import config.settings in a clean subprocess with the given environment."""
    env = {k: v for k, v in os.environ.items() if k.startswith(('PATH', 'SYSTEMROOT', 'PYTHON', 'TEMP', 'TMP', 'HOME'))}
    env.update({k: v for k, v in overrides.items() if v is not None})
    code = (
        'import json; from config import settings as s; '
        'print(json.dumps({"debug": s.DEBUG, "cache": s.CACHES["default"]["LOCATION"], '
        '"sessions": s.CACHES["sessions"]["LOCATION"], "broker": s.CELERY_BROKER_URL, '
        '"result": s.CELERY_RESULT_BACKEND, "secure": s.SESSION_COOKIE_SECURE, '
        '"origins": s.CORS_ALLOWED_ORIGINS, "csrf": s.CSRF_TRUSTED_ORIGINS, "db": s.DATABASES["default"]["ENGINE"], '
        '"minlen": s.AUTH_PASSWORD_VALIDATORS[0]["OPTIONS"]["min_length"], "hosts": s.ALLOWED_HOSTS, '
        '"database": {k: v for k, v in s.DATABASES["default"].items()}, "silenced": s.SILENCED_SYSTEM_CHECKS}))'
    )
    return subprocess.run([sys.executable, '-c', code], cwd=BASE_DIR, env=env, capture_output=True, text=True, timeout=60)


class TestSettingsInFreshProcess:
    def test_secret_key_is_required_when_debug_is_off(self):
        result = load_settings(DJANGO_DEBUG='false', DATABASE_ENGINE='sqlite')
        assert result.returncode != 0
        assert 'DJANGO_SECRET_KEY' in result.stderr

    def test_debug_mode_falls_back_to_an_insecure_dev_key(self):
        result = load_settings(DJANGO_DEBUG='true', DATABASE_ENGINE='sqlite')
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)['debug'] is True

    def test_unknown_database_engine_is_rejected(self):
        result = load_settings(DJANGO_DEBUG='true', DATABASE_ENGINE='oracle')
        assert result.returncode != 0
        assert 'DATABASE_ENGINE' in result.stderr

    def test_redis_urls_are_composed_per_purpose(self):
        result = load_settings(
            DJANGO_SECRET_KEY='k', DATABASE_ENGINE='sqlite',
            REDIS_URL='redis://:pw@cache:6380/', REDIS_CACHE_DB='5', REDIS_SESSION_DB='6', REDIS_BROKER_DB='7', REDIS_RESULT_DB='8',
        )
        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout)
        assert data['cache'] == 'redis://:pw@cache:6380/5'
        assert data['sessions'] == 'redis://:pw@cache:6380/6'
        assert data['broker'] == 'redis://:pw@cache:6380/7'
        assert data['result'] == 'redis://:pw@cache:6380/8'

    def test_explicit_broker_url_wins(self):
        result = load_settings(DJANGO_SECRET_KEY='k', DATABASE_ENGINE='sqlite', CELERY_BROKER_URL='redis://other:1/9')
        assert json.loads(result.stdout)['broker'] == 'redis://other:1/9'

    def test_secure_cookies_default_on_when_not_debugging(self):
        prod = json.loads(load_settings(DJANGO_SECRET_KEY='k', DATABASE_ENGINE='sqlite', DJANGO_DEBUG='false').stdout)
        dev = json.loads(load_settings(DJANGO_DEBUG='true', DATABASE_ENGINE='sqlite').stdout)
        assert prod['secure'] is True and dev['secure'] is False

    def test_secure_cookie_flag_can_be_overridden(self):
        data = json.loads(load_settings(DJANGO_SECRET_KEY='k', DATABASE_ENGINE='sqlite', SESSION_COOKIE_SECURE='false').stdout)
        assert data['secure'] is False

    def test_cors_and_csrf_origins_follow_frontend_url_by_default(self):
        data = json.loads(load_settings(DJANGO_SECRET_KEY='k', DATABASE_ENGINE='sqlite', FRONTEND_URL='https://techomato.com/').stdout)
        assert 'https://techomato.com' in data['origins']
        assert data['csrf'] == data['origins']

    def test_explicit_origin_lists(self):
        data = json.loads(load_settings(
            DJANGO_SECRET_KEY='k', DATABASE_ENGINE='sqlite',
            CORS_ALLOWED_ORIGINS='https://a.example,https://b.example', CSRF_TRUSTED_ORIGINS='https://c.example',
        ).stdout)
        assert data['origins'] == ['https://a.example', 'https://b.example']
        assert data['csrf'] == ['https://c.example']

    def test_password_min_length_is_configurable(self):
        data = json.loads(load_settings(DJANGO_SECRET_KEY='k', DATABASE_ENGINE='sqlite', PASSWORD_MIN_LENGTH='12').stdout)
        assert data['minlen'] == 12

    def test_postgres_is_the_default_engine(self):
        data = json.loads(load_settings(DJANGO_SECRET_KEY='k').stdout)
        assert data['db'] == 'django.db.backends.postgresql'

    def test_allowed_hosts_are_configurable(self):
        data = json.loads(load_settings(DJANGO_SECRET_KEY='k', DATABASE_ENGINE='sqlite', DJANGO_ALLOWED_HOSTS='api.techomato.com, localhost').stdout)
        assert data['hosts'] == ['api.techomato.com', 'localhost']


class TestDjangoExceptionCodes:
    def test_permission_denied_and_404_codes(self):
        from django.core.exceptions import PermissionDenied
        from django.http import Http404

        denied = core_exceptions.api_exception_handler(PermissionDenied(), {})
        missing = core_exceptions.api_exception_handler(Http404(), {})
        assert (denied.status_code, denied.data['code']) == (403, 'permission_denied')
        assert (missing.status_code, missing.data['code']) == (404, 'not_found')


def test_wsgi_and_asgi_entrypoints_load():
    from config.asgi import application as asgi_app
    from config.wsgi import application as wsgi_app

    assert callable(wsgi_app) and callable(asgi_app)
