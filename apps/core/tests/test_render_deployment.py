"""Everything specific to hosting on Render: DATABASE_URL, hostnames, health probe, blueprint."""
import json
from pathlib import Path

import pytest
import yaml
from django.test import Client

from apps.core.tests.test_helpers_and_settings import load_settings

BASE = Path(__file__).resolve().parents[3]
STRONG_SECRET = 'q7Vn3xLk9ZpR2mWc8YhT5bJd6FgA1sUe4oNi0KtXvEyB'


def settings_from(**env):
    result = load_settings(DJANGO_SECRET_KEY=STRONG_SECRET, **env)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


# ------------------------------------------------------------- DATABASE_URL
class TestDatabaseUrl:
    def test_render_style_internal_url(self):
        db = settings_from(DATABASE_URL='postgresql://techomato:s3cret@dpg-abc123-a/techomato')['database']
        assert db['ENGINE'] == 'django.db.backends.postgresql'
        assert (db['NAME'], db['USER'], db['PASSWORD'], db['HOST'], db['PORT']) == (
            'techomato', 'techomato', 's3cret', 'dpg-abc123-a', '5432',
        )
        assert db['CONN_HEALTH_CHECKS'] is True and 'OPTIONS' not in db

    def test_explicit_port_and_scheme_alias(self):
        db = settings_from(DATABASE_URL='postgres://u:p@db.example.com:6543/app')['database']
        assert db['HOST'] == 'db.example.com' and db['PORT'] == '6543' and db['NAME'] == 'app'

    def test_special_characters_in_the_password_are_decoded(self):
        db = settings_from(DATABASE_URL='postgresql://user:p%40ss%2Fw%3Ard%23@host/name')['database']
        assert db['PASSWORD'] == 'p@ss/w:rd#'

    def test_sslmode_is_passed_through(self):
        db = settings_from(DATABASE_URL='postgresql://u:p@host.render.com/app?sslmode=require')['database']
        assert db['OPTIONS'] == {'sslmode': 'require'}

    def test_url_wins_over_individual_variables(self):
        db = settings_from(DATABASE_URL='postgresql://u:p@urlhost/urldb', POSTGRES_HOST='other', POSTGRES_DB='other')['database']
        assert db['HOST'] == 'urlhost' and db['NAME'] == 'urldb'

    @pytest.mark.parametrize('url', ['mysql://u:p@h/db', 'postgresql://u:p@h', 'postgresql:///db', 'not-a-url'])
    def test_bad_urls_fail_fast_with_a_clear_message(self, url):
        result = load_settings(DJANGO_SECRET_KEY=STRONG_SECRET, DATABASE_URL=url)
        assert result.returncode != 0
        assert 'DATABASE_URL' in result.stderr

    def test_blank_url_falls_back_to_individual_variables(self):
        db = settings_from(DATABASE_URL='', POSTGRES_HOST='dbhost', POSTGRES_DB='mydb')['database']
        assert db['HOST'] == 'dbhost' and db['NAME'] == 'mydb'


# ------------------------------------------------------------------- hosts
class TestRenderHostname:
    def test_external_hostname_is_allowed_automatically(self):
        hosts = settings_from(DATABASE_ENGINE='sqlite', DJANGO_ALLOWED_HOSTS='api.techomato.com', RENDER_EXTERNAL_HOSTNAME='techomato-api.onrender.com')['hosts']
        assert hosts == ['api.techomato.com', 'techomato-api.onrender.com']

    def test_no_duplicate_when_already_listed(self):
        hosts = settings_from(DATABASE_ENGINE='sqlite', DJANGO_ALLOWED_HOSTS='x.onrender.com', RENDER_EXTERNAL_HOSTNAME='x.onrender.com')['hosts']
        assert hosts == ['x.onrender.com']

    def test_nothing_added_outside_render(self):
        hosts = settings_from(DATABASE_ENGINE='sqlite', DJANGO_ALLOWED_HOSTS='api.techomato.com')['hosts']
        assert hosts == ['api.techomato.com']

    def test_django_length_only_secret_check_is_replaced_by_ours(self):
        assert 'security.W009' in settings_from(DATABASE_ENGINE='sqlite')['silenced']


# ------------------------------------------------------------ health probe
class TestHealthProbe:
    def test_answers_for_any_host_header(self, settings):
        client = Client()
        for host in ('10.1.2.3:10000', 'techomato-api-xyz.internal', 'evil.example'):
            response = client.get('/api/v1/health/', HTTP_HOST=host)
            assert response.status_code == 200, host
            assert response.json() == {'status': 'ok', 'database': 'ok', 'cache': 'ok'}

    def test_supports_head(self):
        assert Client().head('/api/v1/health/', HTTP_HOST='10.0.0.1').status_code == 200

    def test_other_paths_still_validate_the_host(self):
        client = Client()
        assert client.get('/api/v1/gallery/', HTTP_HOST='evil.example').status_code == 400
        assert client.get('/api/v1/gallery/', HTTP_HOST='testserver').status_code == 200

    def test_only_get_and_head_are_answered(self):
        assert Client().post('/api/v1/health/', HTTP_HOST='testserver').status_code == 405

    def test_middleware_runs_before_host_validation(self, settings):
        assert settings.MIDDLEWARE[0] == 'apps.core.middleware.HealthCheckMiddleware'


class TestClientIpDiagnostic:
    def test_reports_the_callers_own_address_details(self, client, settings):
        settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, 'NUM_PROXIES': 0}
        body = client.get('/api/v1/health/?debug=ip', REMOTE_ADDR='203.0.113.9', HTTP_X_FORWARDED_FOR='198.51.100.7').json()
        assert body['client']['remoteAddr'] == '203.0.113.9'
        assert body['client']['xForwardedFor'] == '198.51.100.7'
        assert body['client']['ident'] == '203.0.113.9'  # 0 proxies: the socket peer is used

    def test_ident_follows_the_trusted_proxy_count(self, client, settings):
        from rest_framework.settings import api_settings
        from rest_framework.throttling import BaseThrottle  # noqa: F401

        settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, 'NUM_PROXIES': 1}
        api_settings.reload()
        try:
            xff = '6.6.6.6, 198.51.100.7'  # left value is client-controlled, right value added by the platform
            body = client.get('/api/v1/health/?debug=ip', HTTP_X_FORWARDED_FOR=xff).json()
            assert body['client']['ident'] == '198.51.100.7'
            assert body['client']['numProxies'] == 1
        finally:
            settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, 'NUM_PROXIES': 0}
            api_settings.reload()

    def test_absent_unless_requested(self, client):
        assert 'client' not in client.get('/api/v1/health/').json()
        assert 'client' not in client.get('/api/v1/health/?debug=nope').json()


# -------------------------------------------------------------- blueprint
@pytest.fixture(scope='module')
def blueprint():
    return yaml.safe_load((BASE / 'render.yaml').read_text(encoding='utf-8'))


def service(blueprint, name):
    return next(s for s in blueprint['services'] if s['name'] == name)


def env_map(entries):
    return {e['key']: e for e in entries if 'key' in e}


class TestBlueprint:
    def test_has_the_four_resources(self, blueprint):
        kinds = {s['name']: s['type'] for s in blueprint['services']}
        assert kinds == {'techomato-redis': 'keyvalue', 'techomato-api': 'web', 'techomato-worker': 'worker'}
        assert [d['name'] for d in blueprint['databases']] == ['techomato-db']

    def test_everything_shares_one_region_for_private_networking(self, blueprint):
        regions = {s['region'] for s in blueprint['services']} | {d['region'] for d in blueprint['databases']}
        assert len(regions) == 1

    def test_docker_services_point_at_real_files(self, blueprint):
        for name in ('techomato-api', 'techomato-worker'):
            svc = service(blueprint, name)
            assert svc['runtime'] == 'docker'
            assert (BASE / svc['dockerfilePath']).is_file()

    def test_web_service_settings(self, blueprint):
        web = service(blueprint, 'techomato-api')
        assert web['healthCheckPath'] == '/api/v1/health/'
        assert web['preDeployCommand'] == 'sh scripts/predeploy.sh'
        assert (BASE / 'scripts' / 'predeploy.sh').is_file()
        assert web['domains'] == ['api.techomato.com']

    def test_worker_runs_celery_against_the_app(self, blueprint):
        worker = service(blueprint, 'techomato-worker')
        assert worker['dockerCommand'].startswith('celery -A config worker')

    def test_connection_strings_come_from_the_managed_services(self, blueprint):
        for name in ('techomato-api', 'techomato-worker'):
            env = env_map(service(blueprint, name)['envVars'])
            assert env['DATABASE_URL']['fromDatabase'] == {'name': 'techomato-db', 'property': 'connectionString'}
            assert env['REDIS_URL']['fromService'] == {'type': 'keyvalue', 'name': 'techomato-redis', 'property': 'connectionString'}

    def test_both_services_use_the_shared_group_so_secret_keys_match(self, blueprint):
        group = next(g for g in blueprint['envVarGroups'] if g['name'] == 'techomato-shared')
        assert env_map(group['envVars'])['DJANGO_SECRET_KEY'] == {'key': 'DJANGO_SECRET_KEY', 'generateValue': True}
        for name in ('techomato-api', 'techomato-worker'):
            assert {'fromGroup': 'techomato-shared'} in service(blueprint, name)['envVars']

    def test_stateful_services_are_private(self, blueprint):
        assert blueprint['databases'][0]['ipAllowList'] == []
        redis = service(blueprint, 'techomato-redis')
        assert redis['ipAllowList'] == [] and redis['maxmemoryPolicy'] == 'noeviction'

    def test_secrets_are_prompted_never_committed(self, blueprint):
        web = env_map(service(blueprint, 'techomato-api')['envVars'])
        worker = env_map(service(blueprint, 'techomato-worker')['envVars'])
        for key in ('ADMIN_EMAIL', 'ADMIN_PASSWORD', 'DJANGO_ADMIN_URL', 'GOOGLE_CLIENT_SECRET', 'GITHUB_CLIENT_SECRET'):
            assert web[key] == {'key': key, 'sync': False}
        for key in ('EMAIL_HOST_USER', 'EMAIL_HOST_PASSWORD'):
            assert worker[key] == {'key': key, 'sync': False}
        text = (BASE / 'render.yaml').read_text(encoding='utf-8')
        assert 'CircuitAdmin' not in text and 'techomato_dev_password' not in text

    def test_shared_settings_are_production_safe(self, blueprint):
        group = next(g for g in blueprint['envVarGroups'] if g['name'] == 'techomato-shared')
        env = {k: v.get('value') for k, v in env_map(group['envVars']).items()}
        assert env['DJANGO_DEBUG'] == 'false'
        assert env['SESSION_COOKIE_SECURE'] == 'true' and env['CSRF_COOKIE_SECURE'] == 'true'
        assert env['USE_X_FORWARDED_PROTO'] == 'true'
        assert env['FRONTEND_URL'].startswith('https://')
        assert all(env[k].startswith('https://') for k in ('CORS_ALLOWED_ORIGINS', 'CSRF_TRUSTED_ORIGINS'))
        assert {env[k] for k in ('REDIS_CACHE_DB', 'REDIS_SESSION_DB', 'REDIS_BROKER_DB', 'REDIS_RESULT_DB')} == {'0'}
        assert int(env['SECURE_HSTS_SECONDS']) > 0
        assert env['EMAIL_BACKEND'].endswith('smtp.EmailBackend')

    def test_release_tasks_are_moved_out_of_the_web_start_up(self, blueprint):
        web = env_map(service(blueprint, 'techomato-api')['envVars'])
        assert web['RUN_RELEASE_TASKS']['value'] == 'false'


# ----------------------------------------------------------------- scripts
class TestScripts:
    def test_predeploy_script_does_the_release_steps_in_order(self):
        script = (BASE / 'scripts' / 'predeploy.sh').read_text()
        order = [script.index(cmd) for cmd in ('check --deploy', 'manage.py migrate', 'ensure_admin', 'seed_gallery')]
        assert order == sorted(order)
        assert script.startswith('#!/bin/sh') and 'set -eu' in script

    def test_web_start_only_runs_release_tasks_when_asked(self):
        script = (BASE / 'scripts' / 'start-web.sh').read_text()
        assert 'RUN_RELEASE_TASKS:-true' in script
        gate = script.index('RUN_RELEASE_TASKS')
        assert gate < script.index('manage.py migrate') < script.index('collectstatic')

    def test_web_start_binds_to_the_platform_port(self):
        assert '${PORT:-8000}' in (BASE / 'scripts' / 'start-web.sh').read_text()


# ---------------------------------------------- production cookie behaviour
class TestSecureCookies:
    def test_session_and_csrf_cookies_are_secure_and_the_session_still_works(self, settings, user):
        settings.SESSION_COOKIE_SECURE = True
        settings.CSRF_COOKIE_SECURE = True
        client = Client(HTTP_HOST='testserver', HTTP_X_FORWARDED_PROTO='https')
        login = client.post(
            '/api/v1/auth/login/',
            data=json.dumps({'email': user.email, 'password': 'correct-horse-9'}),
            content_type='application/json',
        )
        assert login.status_code == 200
        assert login.cookies[settings.SESSION_COOKIE_NAME]['secure']
        assert login.cookies[settings.SESSION_COOKIE_NAME]['httponly']
        assert client.get('/api/v1/auth/csrf/').cookies['csrftoken']['secure']
        # browsers send Secure cookies back over HTTPS; the test client always sends them
        assert client.get('/api/v1/auth/me/').json()['id'] == str(user.id)

    def test_cross_site_deployments_can_use_samesite_none(self):
        data = settings_from(DATABASE_ENGINE='sqlite', SESSION_COOKIE_SAMESITE='None', CSRF_COOKIE_SAMESITE='None')
        assert data['origins'] is not None  # settings still load with the cross-site combination
