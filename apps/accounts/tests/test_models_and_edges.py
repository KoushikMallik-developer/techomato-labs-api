import uuid
from unittest import mock

import pytest
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from apps.accounts import oauth
from apps.accounts.models import SocialAccount, User, make_handle_base
from conftest import PASSWORD


class TestUserModel:
    def test_str_and_email_normalisation(self, make_user):
        user = make_user('  MiXed@Example.COM ')
        assert str(user) == 'mixed@example.com'
        assert User.objects.get_by_email(' MIXED@example.com ') == user
        assert User.objects.get_by_email('') is None
        assert User.objects.get_by_email(None) is None

    def test_email_is_required(self):
        with pytest.raises(ValueError):
            User.objects.create_user('', 'password-123', name='x')

    def test_create_user_without_password_has_unusable_password(self):
        user = User.objects.create_user('nopw@example.com', None, name='No Pw')
        assert not user.has_usable_password()

    def test_create_superuser(self):
        admin = User.objects.create_superuser('root@example.com', 'super-secret-1', name='Root')
        assert admin.is_staff and admin.is_superuser and admin.verified
        assert admin.check_password('super-secret-1')

    def test_regular_users_are_not_staff_by_default(self, make_user):
        user = make_user()
        assert not user.is_staff and not user.is_superuser

    def test_emails_are_unique_at_the_database_level(self, make_user):
        make_user('dup@example.com')
        with pytest.raises(IntegrityError), transaction.atomic():
            User.objects.create(email='dup@example.com', name='Other')

    @pytest.mark.parametrize(
        'name, expected',
        [
            ('Sam', 'sam'),
            ("  Emile O'Neil!!  ", 'emileoneil'),
            ('!!!', 'user'),
            ('', 'user'),
            (None, 'user'),
            ('A' * 40, 'a' * 16),
            ('Ada Lovelace 99', 'adalovelace99'),
        ],
    )
    def test_handle_base(self, name, expected):
        assert make_handle_base(name) == expected

    def test_handle_widens_the_suffix_on_collision(self, make_user):
        wanted_id = uuid.uuid4()
        make_user('first@example.com', name='Sam', handle=f'sam_{wanted_id.hex[-4:]}')
        second = make_user('second@example.com', name='Sam', id=wanted_id)
        assert second.handle == f'sam_{wanted_id.hex[-6:]}'

    def test_handle_is_only_generated_once(self, make_user):
        user = make_user(name='Original')
        handle = user.handle
        user.name = 'Completely Different'
        user.save()
        user.refresh_from_db()
        assert user.handle == handle

    def test_handle_for_names_with_no_letters(self, make_user):
        user = make_user(name='\U0001F680\U0001F680')
        assert user.handle.startswith('user_')


class TestSocialAccountModel:
    def test_str_and_uniqueness(self, make_user):
        user = make_user()
        link = SocialAccount.objects.create(user=user, provider='google', uid='123')
        assert str(link) == 'google:123'
        with pytest.raises(IntegrityError), transaction.atomic():
            SocialAccount.objects.create(user=make_user(), provider='google', uid='123')

    def test_same_uid_on_different_providers_is_fine(self, make_user):
        user = make_user()
        SocialAccount.objects.create(user=user, provider='google', uid='123')
        SocialAccount.objects.create(user=user, provider='github', uid='123')
        assert user.social_accounts.count() == 2

    def test_links_are_removed_with_the_user(self, make_user):
        user = make_user()
        SocialAccount.objects.create(user=user, provider='google', uid='9')
        user.delete()
        assert SocialAccount.objects.count() == 0


class TestSignupEdges:
    def test_lost_race_on_duplicate_email_is_a_clean_400(self, client):
        with mock.patch.object(User.objects, 'create_user', side_effect=IntegrityError('duplicate')):
            response = client.post(
                '/api/v1/auth/signup/',
                {'name': 'Racer', 'email': 'race@example.com', 'password': PASSWORD},
                format='json',
            )
        assert response.status_code == 400
        assert response.json()['detail'] == 'An account with that email already exists.'

    def test_failed_signup_leaves_no_partial_data(self, client):
        from apps.projects.models import Project

        with mock.patch('apps.accounts.views.create_starter_project', side_effect=RuntimeError('boom')):
            with pytest.raises(RuntimeError):
                client.post(
                    '/api/v1/auth/signup/',
                    {'name': 'Half', 'email': 'half@example.com', 'password': PASSWORD},
                    format='json',
                )
        assert not User.objects.filter(email='half@example.com').exists()
        assert Project.objects.count() == 0

    def test_emoji_only_name_still_gets_a_handle(self, client):
        response = client.post(
            '/api/v1/auth/signup/',
            {'name': '\U0001F680', 'email': 'rocket@example.com', 'password': PASSWORD},
            format='json',
        )
        assert response.status_code == 201
        assert response.json()['handle'].startswith('user_')

    def test_password_is_never_returned_or_stored_in_clear(self, client):
        response = client.post(
            '/api/v1/auth/signup/',
            {'name': 'Safe', 'email': 'safe@example.com', 'password': PASSWORD},
            format='json',
        )
        assert PASSWORD not in response.content.decode()
        assert User.objects.get(email='safe@example.com').password != PASSWORD


class TestOAuthOnlyAccounts:
    @pytest.fixture
    def oauth_user(self, make_user):
        user = make_user('social@example.com', password=None, name='Social')
        SocialAccount.objects.create(user=user, provider='google', uid='g1')
        return user

    def test_cannot_log_in_with_a_password(self, client, oauth_user):
        for password in ('', 'anything-at-all-1', 'None'):
            response = client.post('/api/v1/auth/login/', {'email': oauth_user.email, 'password': password}, format='json')
            assert response.status_code == 400

    def test_can_use_password_reset_to_add_a_password(self, client, oauth_user, django_capture_on_commit_callbacks):
        from django.core import mail

        with django_capture_on_commit_callbacks(execute=True):
            client.post('/api/v1/auth/password/forgot/', {'email': oauth_user.email}, format='json')
        token = mail.outbox[-1].body.split('token=')[1].split()[0]
        assert client.post('/api/v1/auth/password/reset/', {'token': token, 'password': 'new-social-pass-1'}, format='json').status_code == 204
        oauth_user.refresh_from_db()
        assert oauth_user.has_usable_password()
        assert client.post('/api/v1/auth/login/', {'email': oauth_user.email, 'password': 'new-social-pass-1'}, format='json').status_code == 200

    def test_me_reports_provider_and_no_password(self, oauth_user):
        api = APIClient()
        api.force_login(oauth_user)
        body = api.get('/api/v1/auth/me/').json()
        assert body['providers'] == ['google'] and body['hasPassword'] is False


class TestInactiveAndTokens:
    def test_inactive_user_gets_no_reset_mail(self, client, user, django_capture_on_commit_callbacks):
        from django.core import mail

        user.is_active = False
        user.save()
        with django_capture_on_commit_callbacks(execute=True):
            assert client.post('/api/v1/auth/password/forgot/', {'email': user.email}, format='json').status_code == 202
        assert mail.outbox == []

    def test_verification_token_for_inactive_user_is_refused(self, client, make_user):
        from apps.accounts.tokens import make_verification_token

        user = make_user(verified=False)
        token = make_verification_token(user)
        user.is_active = False
        user.save()
        assert client.post('/api/v1/auth/verify-email/', {'token': token}, format='json').status_code == 400

    def test_verification_token_for_deleted_user_is_refused(self, client, make_user):
        from apps.accounts.tokens import make_verification_token

        user = make_user(verified=False)
        token = make_verification_token(user)
        user.delete()
        assert client.post('/api/v1/auth/verify-email/', {'token': token}, format='json').status_code == 400

    def test_reset_token_is_invalidated_by_a_login(self, client, user, django_capture_on_commit_callbacks):
        """Django ties reset tokens to last_login, so signing in kills outstanding links."""
        from django.core import mail

        with django_capture_on_commit_callbacks(execute=True):
            client.post('/api/v1/auth/password/forgot/', {'email': user.email}, format='json')
        token = mail.outbox[-1].body.split('token=')[1].split()[0]
        client.post('/api/v1/auth/login/', {'email': user.email, 'password': PASSWORD}, format='json')
        assert client.post('/api/v1/auth/password/reset/', {'token': token, 'password': 'whatever-pass-12'}, format='json').status_code == 400

    def test_avatar_length_limit(self, auth_client):
        assert auth_client.patch('/api/v1/auth/me/', {'avatar': 'x' * 33}, format='json').status_code == 400
        assert auth_client.patch('/api/v1/auth/me/', {'avatar': ''}, format='json').status_code == 200


class TestOAuthProviderEdges:
    def test_unknown_provider_credentials(self):
        with pytest.raises(KeyError):
            oauth.credentials('myspace')

    def test_google_userinfo_without_email(self):
        def resp(payload):
            r = mock.Mock()
            r.json.return_value = payload
            return r

        with mock.patch('apps.accounts.oauth.requests.request', side_effect=[resp({'access_token': 't'}), resp({'sub': '1'})]):
            with pytest.raises(oauth.OAuthError):
                oauth.fetch_identity('google', 'c', 'r')

    def test_google_name_falls_back_to_email_local_part(self):
        def resp(payload):
            r = mock.Mock()
            r.json.return_value = payload
            return r

        replies = [resp({'access_token': 't'}), resp({'sub': '1', 'email': 'someone@gmail.com', 'email_verified': True})]
        with mock.patch('apps.accounts.oauth.requests.request', side_effect=replies):
            assert oauth.fetch_identity('google', 'c', 'r').name == 'someone'

    def test_github_error_description_is_surfaced(self):
        reply = mock.Mock()
        reply.json.return_value = {'error': 'bad_verification_code', 'error_description': 'The code passed is incorrect'}
        with mock.patch('apps.accounts.oauth.requests.request', return_value=reply):
            with pytest.raises(oauth.OAuthError, match='incorrect'):
                oauth.fetch_identity('github', 'c', 'r')

    def test_github_name_falls_back_to_login(self):
        def resp(payload):
            r = mock.Mock()
            r.json.return_value = payload
            return r

        replies = [
            resp({'access_token': 't'}),
            resp({'id': 5, 'login': 'octocat', 'name': ''}),
            resp([{'email': 'o@x.com', 'primary': True, 'verified': True}]),
        ]
        with mock.patch('apps.accounts.oauth.requests.request', side_effect=replies):
            assert oauth.fetch_identity('github', 'c', 'r').name == 'octocat'

    def test_non_json_provider_response_is_an_oauth_error(self):
        reply = mock.Mock()
        reply.json.side_effect = ValueError('not json')
        with mock.patch('apps.accounts.oauth.requests.request', return_value=reply):
            with pytest.raises(oauth.OAuthError):
                oauth.fetch_identity('google', 'c', 'r')
