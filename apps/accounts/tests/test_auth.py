import re

import pytest
from django.core import mail
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle

from apps.accounts.models import User
from apps.projects.models import Project
from conftest import PASSWORD

SIGNUP = '/api/v1/auth/signup/'
LOGIN = '/api/v1/auth/login/'
LOGOUT = '/api/v1/auth/logout/'
ME = '/api/v1/auth/me/'


def signup_payload(**over):
    return {'name': 'Casey Kim', 'email': 'casey@example.com', 'password': PASSWORD, **over}


def token_from_mail(message):
    match = re.search(r'token=([^\s]+)', message.body)
    assert match, message.body
    return match.group(1)


# ------------------------------------------------------------------ signup
class TestSignup:
    def test_creates_account_session_and_starter_project(self, client, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            response = client.post(SIGNUP, signup_payload(), format='json')
        assert response.status_code == 201
        body = response.json()
        assert body['email'] == 'casey@example.com'
        assert body['name'] == 'Casey Kim'
        assert body['verified'] is False
        assert re.match(r'^caseykim_[0-9a-f]{4}$', body['handle'])
        assert 'password' not in body and 'pass' not in body
        assert isinstance(body['createdAt'], int)

        user = User.objects.get(email='casey@example.com')
        assert user.check_password(PASSWORD)
        starter = Project.objects.get(owner=user)
        assert starter.name == 'My first circuit'
        assert starter.parts and starter.wires and starter.code

        # signed in
        assert client.get(ME).json()['email'] == 'casey@example.com'

    def test_sends_verification_email(self, client, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            client.post(SIGNUP, signup_payload(), format='json')
        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        assert message.to == ['casey@example.com']
        assert 'http://frontend.test/verify-email?token=' in message.body

    def test_email_is_normalised_and_unique_case_insensitively(self, client):
        assert client.post(SIGNUP, signup_payload(email='  Casey@Example.COM '), format='json').status_code == 201
        assert User.objects.filter(email='casey@example.com').count() == 1
        other = APIClient()
        response = other.post(SIGNUP, signup_payload(email='CASEY@example.com'), format='json')
        assert response.status_code == 400
        assert response.json()['detail'] == 'An account with that email already exists.'

    @pytest.mark.parametrize(
        'override, fragment',
        [
            ({'name': ''}, 'name'),
            ({'name': '   '}, 'name'),
            ({'email': ''}, 'email'),
            ({'email': 'not-an-email'}, 'valid email'),
            ({'password': 'short'}, 'too short'),
            ({'password': 'password'}, 'too common'),
            ({'password': '1234567890'}, 'entirely numeric'),
        ],
    )
    def test_rejects_invalid_input(self, client, override, fragment):
        response = client.post(SIGNUP, signup_payload(**override), format='json')
        assert response.status_code == 400
        assert fragment in str(response.json()).lower()
        assert not User.objects.filter(email='casey@example.com').exists()

    def test_missing_fields(self, client):
        response = client.post(SIGNUP, {}, format='json')
        assert response.status_code == 400
        assert set(response.json()['errors']) == {'name', 'email', 'password'}

    def test_handles_are_unique_for_identical_names(self, make_user):
        a = make_user('a@example.com', name='Sam')
        b = make_user('b@example.com', name='Sam')
        assert a.handle != b.handle
        assert a.handle.startswith('sam_') and b.handle.startswith('sam_')

    def test_handle_is_stable_across_renames(self, auth_client, user):
        before = user.handle
        response = auth_client.patch(ME, {'name': 'Totally New Name'}, format='json')
        assert response.status_code == 200
        assert response.json()['handle'] == before


# ------------------------------------------------------------------- login
class TestLogin:
    def test_success(self, client, user):
        response = client.post(LOGIN, {'email': 'Alice@Example.com', 'password': PASSWORD}, format='json')
        assert response.status_code == 200
        assert response.json()['id'] == str(user.id)
        assert client.get(ME).status_code == 200

    @pytest.mark.parametrize('email, password', [
        ('alice@example.com', 'wrong-password-1'),
        ('nobody@example.com', PASSWORD),
    ])
    def test_bad_credentials_share_one_message(self, client, user, email, password):
        response = client.post(LOGIN, {'email': email, 'password': password}, format='json')
        assert response.status_code == 400
        assert response.json()['detail'] == 'Email or password is incorrect.'
        assert client.get(ME).status_code == 401

    def test_inactive_user_cannot_log_in(self, client, user):
        user.is_active = False
        user.save()
        response = client.post(LOGIN, {'email': user.email, 'password': PASSWORD}, format='json')
        assert response.status_code == 400

    def test_is_throttled(self, client, user, monkeypatch):
        monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, 'auth', '3/min')
        codes = [
            client.post(LOGIN, {'email': user.email, 'password': 'wrong-password-1'}, format='json').status_code
            for _ in range(5)
        ]
        assert codes[:3] == [400, 400, 400]
        assert codes[3:] == [429, 429]
        throttled = client.post(LOGIN, {'email': user.email, 'password': 'x'}, format='json')
        assert throttled.json()['retryAfter'] > 0 and throttled.json()['detail']

    def test_logout(self, auth_client):
        assert auth_client.post(LOGOUT).status_code == 204
        assert auth_client.get(ME).status_code == 401

    def test_logout_when_signed_out_is_fine(self, client):
        assert client.post(LOGOUT).status_code == 204


# ----------------------------------------------------------------- profile
class TestMe:
    def test_requires_login(self, client):
        assert client.get(ME).status_code == 401

    def test_get(self, auth_client, user):
        body = auth_client.get(ME).json()
        assert body['id'] == str(user.id)
        assert body['hasPassword'] is True
        assert body['providers'] == []

    def test_update_name_and_avatar(self, auth_client, user):
        response = auth_client.patch(ME, {'name': '  New Name ', 'avatar': '🚀'}, format='json')
        assert response.status_code == 200
        user.refresh_from_db()
        assert user.name == 'New Name'
        assert user.avatar == '🚀'

    def test_cannot_change_protected_fields(self, auth_client, user):
        auth_client.patch(
            ME,
            {'email': 'evil@example.com', 'verified': False, 'is_staff': True, 'handle': 'hacked'},
            format='json',
        )
        user.refresh_from_db()
        assert user.email == 'alice@example.com'
        assert user.is_staff is False
        assert user.handle != 'hacked'

    def test_blank_name_rejected(self, auth_client):
        assert auth_client.patch(ME, {'name': '  '}, format='json').status_code == 400

    def test_delete_account_removes_data_and_signs_out(self, auth_client, user, other_user):
        Project.objects.create(owner=user, name='mine')
        Project.objects.create(owner=other_user, name='theirs')
        assert auth_client.delete(ME).status_code == 204
        assert not User.objects.filter(pk=user.pk).exists()
        assert not Project.objects.filter(name='mine').exists()
        assert Project.objects.filter(name='theirs').exists()
        assert auth_client.get(ME).status_code == 401


# ---------------------------------------------------------------- password
class TestChangePassword:
    URL = '/api/v1/auth/password/change/'

    def test_requires_login(self, client):
        assert client.post(self.URL, {'current': PASSWORD, 'next': 'another-pass-1'}, format='json').status_code == 401

    def test_success_keeps_this_session_and_updates_password(self, auth_client, user):
        response = auth_client.post(self.URL, {'current': PASSWORD, 'next': 'another-pass-1'}, format='json')
        assert response.status_code == 204
        assert auth_client.get(ME).status_code == 200
        user.refresh_from_db()
        assert user.check_password('another-pass-1')

    def test_other_sessions_are_signed_out(self, auth_client, user):
        second = APIClient()
        second.post(LOGIN, {'email': user.email, 'password': PASSWORD}, format='json')
        assert second.get(ME).status_code == 200
        auth_client.post(self.URL, {'current': PASSWORD, 'next': 'another-pass-1'}, format='json')
        assert second.get(ME).status_code == 401

    def test_wrong_current_password(self, auth_client, user):
        response = auth_client.post(self.URL, {'current': 'nope-nope-12', 'next': 'another-pass-1'}, format='json')
        assert response.status_code == 400
        assert response.json()['detail'] == 'Current password is incorrect.'
        user.refresh_from_db()
        assert user.check_password(PASSWORD)

    def test_weak_new_password(self, auth_client):
        response = auth_client.post(self.URL, {'current': PASSWORD, 'next': 'short'}, format='json')
        assert response.status_code == 400

    def test_account_without_password_can_set_one(self, make_user):
        user = make_user('oauth@example.com', password=None)
        assert not user.has_usable_password()
        api = APIClient()
        api.force_login(user)
        response = api.post(self.URL, {'next': 'brand-new-pass-1'}, format='json')
        assert response.status_code == 204
        user.refresh_from_db()
        assert user.check_password('brand-new-pass-1')


class TestPasswordReset:
    FORGOT = '/api/v1/auth/password/forgot/'
    RESET = '/api/v1/auth/password/reset/'

    def request_token(self, client, email, capture):
        with capture(execute=True):
            response = client.post(self.FORGOT, {'email': email}, format='json')
        assert response.status_code == 202
        return token_from_mail(mail.outbox[-1])

    def test_full_flow(self, client, user, django_capture_on_commit_callbacks):
        token = self.request_token(client, user.email, django_capture_on_commit_callbacks)
        assert 'http://frontend.test/reset-password?token=' in mail.outbox[-1].body
        response = client.post(self.RESET, {'token': token, 'password': 'fresh-pass-42'}, format='json')
        assert response.status_code == 204
        user.refresh_from_db()
        assert user.check_password('fresh-pass-42')
        assert client.post(LOGIN, {'email': user.email, 'password': 'fresh-pass-42'}, format='json').status_code == 200

    def test_token_is_single_use(self, client, user, django_capture_on_commit_callbacks):
        token = self.request_token(client, user.email, django_capture_on_commit_callbacks)
        assert client.post(self.RESET, {'token': token, 'password': 'fresh-pass-42'}, format='json').status_code == 204
        again = client.post(self.RESET, {'token': token, 'password': 'other-pass-4242'}, format='json')
        assert again.status_code == 400
        assert again.json()['detail'] == 'That reset link is invalid or has expired.'

    def test_unknown_email_gets_same_answer_and_no_mail(self, client, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            response = client.post(self.FORGOT, {'email': 'ghost@example.com'}, format='json')
        assert response.status_code == 202
        assert mail.outbox == []

    def test_expired_token(self, client, user, django_capture_on_commit_callbacks, settings):
        token = self.request_token(client, user.email, django_capture_on_commit_callbacks)
        settings.PASSWORD_RESET_TIMEOUT = -1
        response = client.post(self.RESET, {'token': token, 'password': 'fresh-pass-42'}, format='json')
        assert response.status_code == 400

    @pytest.mark.parametrize('token', ['', 'garbage', 'abc.def', '....', 'Zm9v.bar-baz'])
    def test_bad_tokens(self, client, token):
        response = client.post(self.RESET, {'token': token, 'password': 'fresh-pass-42'}, format='json')
        assert response.status_code == 400

    def test_token_for_other_user_does_not_work_after_tampering(self, client, user, other_user, django_capture_on_commit_callbacks):
        token = self.request_token(client, user.email, django_capture_on_commit_callbacks)
        _, _, raw = token.partition('.')
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode

        forged = f'{urlsafe_base64_encode(force_bytes(str(other_user.pk)))}.{raw}'
        assert client.post(self.RESET, {'token': forged, 'password': 'fresh-pass-42'}, format='json').status_code == 400
        other_user.refresh_from_db()
        assert other_user.check_password(PASSWORD)

    def test_weak_password_rejected_and_token_still_usable(self, client, user, django_capture_on_commit_callbacks):
        token = self.request_token(client, user.email, django_capture_on_commit_callbacks)
        assert client.post(self.RESET, {'token': token, 'password': 'short'}, format='json').status_code == 400
        assert client.post(self.RESET, {'token': token, 'password': 'fresh-pass-42'}, format='json').status_code == 204

    def test_reset_signs_out_existing_sessions(self, client, auth_client, user, django_capture_on_commit_callbacks):
        token = self.request_token(client, user.email, django_capture_on_commit_callbacks)
        client.post(self.RESET, {'token': token, 'password': 'fresh-pass-42'}, format='json')
        assert auth_client.get(ME).status_code == 401


# ------------------------------------------------------------ verification
class TestEmailVerification:
    VERIFY = '/api/v1/auth/verify-email/'
    RESEND = '/api/v1/auth/verify-email/resend/'

    def test_full_flow(self, client, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            client.post(SIGNUP, signup_payload(), format='json')
        token = token_from_mail(mail.outbox[0])
        response = APIClient().post(self.VERIFY, {'token': token}, format='json')
        assert response.status_code == 200
        assert response.json()['verified'] is True
        assert User.objects.get(email='casey@example.com').verified is True

    def test_verifying_twice_is_harmless(self, client, make_user):
        from apps.accounts.tokens import make_verification_token

        user = make_user(verified=False)
        token = make_verification_token(user)
        assert client.post(self.VERIFY, {'token': token}, format='json').status_code == 200
        assert client.post(self.VERIFY, {'token': token}, format='json').status_code == 200

    def test_invalid_token(self, client):
        response = client.post(self.VERIFY, {'token': 'nonsense'}, format='json')
        assert response.status_code == 400
        assert response.json()['code'] == 'invalid_token'

    def test_expired_token(self, client, make_user, settings):
        from apps.accounts.tokens import make_verification_token

        user = make_user(verified=False)
        token = make_verification_token(user)
        settings.EMAIL_VERIFICATION_MAX_AGE = -1
        assert client.post(self.VERIFY, {'token': token}, format='json').status_code == 400
        user.refresh_from_db()
        assert user.verified is False

    def test_token_dies_when_email_changes(self, client, make_user):
        from apps.accounts.tokens import make_verification_token

        user = make_user(verified=False)
        token = make_verification_token(user)
        user.email = 'changed@example.com'
        user.save()
        assert client.post(self.VERIFY, {'token': token}, format='json').status_code == 400

    def test_resend_requires_login(self, client):
        assert client.post(self.RESEND).status_code == 401

    def test_resend_sends_mail_for_unverified(self, make_user, django_capture_on_commit_callbacks):
        user = make_user(verified=False)
        api = APIClient()
        api.force_login(user)
        with django_capture_on_commit_callbacks(execute=True):
            response = api.post(self.RESEND)
        assert response.status_code == 202
        assert response.json() == {'sent': True}
        assert len(mail.outbox) == 1

    def test_resend_is_a_noop_for_verified(self, auth_client, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            response = auth_client.post(self.RESEND)
        assert response.json() == {'sent': False}
        assert mail.outbox == []

    def test_task_skips_users_verified_meanwhile(self, make_user):
        from apps.accounts import tasks

        user = make_user(verified=True)
        tasks.send_verification_email(str(user.pk))
        assert mail.outbox == []

    def test_signup_survives_broker_outage(self, client, monkeypatch, django_capture_on_commit_callbacks):
        from apps.accounts import tasks

        def boom(*args, **kwargs):
            raise ConnectionError('broker down')

        monkeypatch.setattr(tasks.send_verification_email, 'delay', boom)
        with django_capture_on_commit_callbacks(execute=True):
            response = client.post(SIGNUP, signup_payload(), format='json')
        assert response.status_code == 201
        assert User.objects.filter(email='casey@example.com').exists()


# -------------------------------------------------------------------- CSRF
class TestCsrf:
    def test_csrf_endpoint_returns_token_and_cookie(self, client):
        response = client.get('/api/v1/auth/csrf/')
        assert response.status_code == 200
        assert response.json()['csrfToken']
        assert 'csrftoken' in response.cookies

    def test_signed_in_writes_require_the_token(self, user):
        strict = APIClient(enforce_csrf_checks=True)
        strict.force_login(user)
        assert strict.post('/api/v1/projects/', {'name': 'x'}, format='json').status_code == 403
        token = strict.get('/api/v1/auth/csrf/').json()['csrfToken']
        ok = strict.post('/api/v1/projects/', {'name': 'x'}, format='json', HTTP_X_CSRFTOKEN=token)
        assert ok.status_code == 201

    def test_reads_do_not_need_the_token(self, user):
        strict = APIClient(enforce_csrf_checks=True)
        strict.force_login(user)
        assert strict.get(ME).status_code == 200
