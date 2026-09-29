from io import StringIO
from unittest import mock

import pytest
import requests
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.accounts import oauth
from apps.accounts.models import SocialAccount, User
from apps.projects.models import Project
from conftest import PASSWORD

URL = '/api/v1/auth/oauth/{}/'
BODY = {'code': 'abc', 'redirectUri': 'http://localhost:5173/oauth/callback'}


def identity(**over):
    data = dict(provider='google', uid='g-123', email='new@example.com', email_verified=True, name='New Person')
    data.update(over)
    return oauth.Identity(**data)


@pytest.fixture
def fake_identity(monkeypatch):
    holder = {'value': identity()}
    monkeypatch.setattr(oauth, 'fetch_identity', lambda provider, code, redirect: holder['value'])
    return holder


class TestOAuthLogin:
    def test_first_login_creates_verified_account_with_starter_project(self, client, fake_identity):
        response = client.post(URL.format('google'), BODY, format='json')
        assert response.status_code == 200
        body = response.json()
        assert body['email'] == 'new@example.com'
        assert body['verified'] is True
        assert body['providers'] == ['google']
        assert body['hasPassword'] is False
        user = User.objects.get(email='new@example.com')
        assert Project.objects.filter(owner=user).count() == 1
        assert client.get('/api/v1/auth/me/').status_code == 200

    def test_second_login_reuses_the_account(self, client, fake_identity):
        client.post(URL.format('google'), BODY, format='json')
        client.post('/api/v1/auth/logout/')
        fake_identity['value'] = identity(email='changed-at-google@example.com')  # same uid
        response = client.post(URL.format('google'), BODY, format='json')
        assert response.status_code == 200
        assert User.objects.count() == 1
        assert SocialAccount.objects.count() == 1
        assert Project.objects.count() == 1

    def test_links_to_existing_verified_account_with_same_email(self, client, make_user, fake_identity):
        existing = make_user('new@example.com', verified=True)
        response = client.post(URL.format('google'), BODY, format='json')
        assert response.json()['id'] == str(existing.id)
        existing.refresh_from_db()
        assert existing.check_password(PASSWORD)  # untouched
        assert existing.social_accounts.count() == 1

    def test_linking_an_unverified_local_account_drops_its_password(self, client, make_user, fake_identity):
        """Pre-hijacking defence: the squatter's password must stop working."""
        squatter = make_user('new@example.com', verified=False)
        response = client.post(URL.format('google'), BODY, format='json')
        assert response.status_code == 200
        squatter.refresh_from_db()
        assert squatter.verified is True
        assert not squatter.has_usable_password()
        login = client.post(
            '/api/v1/auth/login/', {'email': 'new@example.com', 'password': PASSWORD}, format='json'
        )
        assert login.status_code == 400

    def test_unverified_provider_email_is_rejected(self, client, fake_identity):
        fake_identity['value'] = identity(email_verified=False)
        response = client.post(URL.format('google'), BODY, format='json')
        assert response.status_code == 400
        assert not User.objects.exists()

    def test_unverified_provider_email_cannot_take_over_existing_account(self, client, make_user, fake_identity):
        make_user('new@example.com')
        fake_identity['value'] = identity(email_verified=False)
        assert client.post(URL.format('google'), BODY, format='json').status_code == 400
        assert not SocialAccount.objects.exists()

    def test_disabled_account_is_refused(self, client, fake_identity):
        client.post(URL.format('google'), BODY, format='json')
        client.post('/api/v1/auth/logout/')
        User.objects.update(is_active=False)
        response = client.post(URL.format('google'), BODY, format='json')
        assert response.status_code == 403

    def test_unknown_provider(self, client):
        assert client.post(URL.format('myspace'), BODY, format='json').status_code == 404

    def test_requires_code_and_redirect_uri(self, client):
        assert client.post(URL.format('google'), {}, format='json').status_code == 400

    def test_provider_failure_is_a_clean_400(self, client, monkeypatch):
        def boom(*args):
            raise oauth.OAuthError('bad code')

        monkeypatch.setattr(oauth, 'fetch_identity', boom)
        response = client.post(URL.format('github'), BODY, format='json')
        assert response.status_code == 400
        assert 'GitHub' in response.json()['detail']

    def test_unconfigured_provider(self, client, settings):
        settings.OAUTH_PROVIDERS = {'google': {'client_id': '', 'client_secret': ''}, 'github': {}}
        response = client.post(URL.format('google'), BODY, format='json')
        assert response.status_code == 503
        assert response.json()['code'] == 'oauth_disabled'

    def test_providers_endpoint_lists_only_configured(self, client, settings):
        settings.OAUTH_PROVIDERS = {
            'google': {'client_id': 'gid', 'client_secret': 's'},
            'github': {'client_id': 'ghid', 'client_secret': ''},
        }
        assert client.get('/api/v1/auth/oauth/providers/').json() == {'google': 'gid'}


def fake_response(payload, status=200):
    response = mock.Mock()
    response.status_code = status
    response.json.return_value = payload
    if status >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(str(status))
    return response


class TestProviderExchange:
    def test_google(self):
        responses = [
            fake_response({'access_token': 'tok'}),
            fake_response({'sub': '42', 'email': 'Me@Gmail.com', 'email_verified': True, 'name': 'Me'}),
        ]
        with mock.patch('apps.accounts.oauth.requests.request', side_effect=responses) as request:
            result = oauth.fetch_identity('google', 'code', 'http://cb')
        assert result == oauth.Identity('google', '42', 'me@gmail.com', True, 'Me')
        token_call = request.call_args_list[0]
        assert token_call.args == ('POST', oauth.GOOGLE_TOKEN_URL)
        assert token_call.kwargs['data']['client_secret'] == 'g-secret'
        assert token_call.kwargs['data']['redirect_uri'] == 'http://cb'
        assert token_call.kwargs['timeout'] > 0
        assert request.call_args_list[1].kwargs['headers']['Authorization'] == 'Bearer tok'

    def test_google_unverified_email_is_reported_as_such(self):
        responses = [fake_response({'access_token': 't'}), fake_response({'sub': '1', 'email': 'a@b.co'})]
        with mock.patch('apps.accounts.oauth.requests.request', side_effect=responses):
            assert oauth.fetch_identity('google', 'c', 'r').email_verified is False

    def test_google_without_access_token(self):
        with mock.patch('apps.accounts.oauth.requests.request', return_value=fake_response({'error': 'x'})):
            with pytest.raises(oauth.OAuthError):
                oauth.fetch_identity('google', 'c', 'r')

    def test_github_uses_primary_verified_email(self):
        responses = [
            fake_response({'access_token': 'tok'}),
            fake_response({'id': 7, 'login': 'octo', 'name': None}),
            fake_response(
                [
                    {'email': 'spare@x.com', 'primary': False, 'verified': True},
                    {'email': 'Main@x.com', 'primary': True, 'verified': True},
                ]
            ),
        ]
        with mock.patch('apps.accounts.oauth.requests.request', side_effect=responses):
            result = oauth.fetch_identity('github', 'code', 'http://cb')
        assert result == oauth.Identity('github', '7', 'main@x.com', True, 'octo')

    def test_github_without_verified_primary_email(self):
        responses = [
            fake_response({'access_token': 'tok'}),
            fake_response({'id': 7, 'login': 'octo'}),
            fake_response([{'email': 'a@x.com', 'primary': True, 'verified': False}]),
        ]
        with mock.patch('apps.accounts.oauth.requests.request', side_effect=responses):
            with pytest.raises(oauth.OAuthError):
                oauth.fetch_identity('github', 'c', 'r')

    def test_network_errors_become_oauth_errors(self):
        with mock.patch('apps.accounts.oauth.requests.request', side_effect=requests.ConnectionError('down')):
            with pytest.raises(oauth.OAuthError):
                oauth.fetch_identity('google', 'c', 'r')

    def test_http_errors_become_oauth_errors(self):
        with mock.patch('apps.accounts.oauth.requests.request', return_value=fake_response({}, status=401)):
            with pytest.raises(oauth.OAuthError):
                oauth.fetch_identity('github', 'c', 'r')

    def test_missing_credentials(self, settings):
        settings.OAUTH_PROVIDERS = {'google': {'client_id': '', 'client_secret': ''}}
        with pytest.raises(oauth.OAuthNotConfigured):
            oauth.fetch_identity('google', 'c', 'r')


class TestEnsureAdminCommand:
    def run(self):
        out = StringIO()
        call_command('ensure_admin', stdout=out)
        return out.getvalue()

    def test_skips_when_not_configured(self, settings):
        settings.ADMIN_EMAIL = ''
        settings.ADMIN_PASSWORD = ''
        assert 'skipping' in self.run()
        assert not User.objects.exists()

    def test_creates_admin(self, settings):
        settings.ADMIN_EMAIL = 'Boss@Example.com'
        settings.ADMIN_PASSWORD = 'admin-pass-123'
        self.run()
        admin = User.objects.get(email='boss@example.com')
        assert admin.is_staff and admin.is_superuser and admin.verified
        assert admin.check_password('admin-pass-123')

    def test_is_idempotent_and_syncs_password(self, settings):
        settings.ADMIN_EMAIL = 'boss@example.com'
        settings.ADMIN_PASSWORD = 'admin-pass-123'
        self.run()
        self.run()
        assert User.objects.count() == 1
        settings.ADMIN_PASSWORD = 'rotated-pass-456'
        self.run()
        assert User.objects.get().check_password('rotated-pass-456')

    def test_promotes_existing_user(self, settings, make_user):
        make_user('boss@example.com', is_staff=False)
        settings.ADMIN_EMAIL = 'boss@example.com'
        settings.ADMIN_PASSWORD = 'admin-pass-123'
        self.run()
        assert User.objects.get().is_staff

    def test_rejects_bad_email(self, settings):
        settings.ADMIN_EMAIL = 'nope'
        settings.ADMIN_PASSWORD = 'admin-pass-123'
        with pytest.raises(CommandError):
            self.run()
