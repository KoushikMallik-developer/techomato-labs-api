import uuid

import pytest
from rest_framework.test import APIClient

from apps.projects.models import Project
from conftest import PASSWORD

LOGIN = '/api/v1/admin/login/'
SESSION = '/api/v1/admin/session/'
PENDING = '/api/v1/admin/circuits/pending/'


def review(pk, verb):
    return f'/api/v1/admin/circuits/{pk}/{verb}/'


@pytest.fixture
def submitted(user):
    return Project.objects.create(owner=user, name='Submitted', published=True, approved=False)


class TestAdminLogin:
    def test_success(self, client, admin_user):
        response = client.post(LOGIN, {'email': 'ADMIN@example.com', 'password': PASSWORD}, format='json')
        assert response.status_code == 200
        assert response.json() == {'email': admin_user.email}
        assert client.get(SESSION).json() == {'isAdmin': True, 'email': admin_user.email}

    def test_regular_users_cannot_sign_in_as_admin(self, client, user):
        response = client.post(LOGIN, {'email': user.email, 'password': PASSWORD}, format='json')
        assert response.status_code == 400
        assert response.json()['detail'] == 'Invalid admin email or password.'
        assert client.get(SESSION).json()['isAdmin'] is False

    @pytest.mark.parametrize('email, password', [('admin@example.com', 'wrong-pass-123'), ('ghost@example.com', PASSWORD)])
    def test_bad_credentials(self, client, admin_user, email, password):
        assert client.post(LOGIN, {'email': email, 'password': password}, format='json').status_code == 400

    def test_admin_signin_does_not_sign_in_a_regular_user(self, admin_client):
        assert admin_client.get('/api/v1/auth/me/').status_code == 401

    def test_regular_signin_does_not_grant_admin(self, auth_client):
        assert auth_client.get(SESSION).json()['isAdmin'] is False
        assert auth_client.get(PENDING).status_code == 401

    def test_deactivated_admin_loses_access(self, admin_client, admin_user):
        admin_user.is_active = False
        admin_user.save()
        assert admin_client.get(SESSION).json()['isAdmin'] is False
        assert admin_client.get(PENDING).status_code == 401

    def test_demoted_admin_loses_access(self, admin_client, admin_user):
        admin_user.is_staff = False
        admin_user.save()
        assert admin_client.get(PENDING).status_code == 401

    def test_logout(self, admin_client):
        assert admin_client.post('/api/v1/admin/logout/').status_code == 204
        assert admin_client.get(SESSION).json()['isAdmin'] is False
        assert admin_client.get(PENDING).status_code == 401

    def test_is_throttled(self, client, monkeypatch):
        from rest_framework.throttling import SimpleRateThrottle

        monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, 'auth', '2/min')
        codes = [client.post(LOGIN, {'email': 'a@b.co', 'password': 'x'}, format='json').status_code for _ in range(4)]
        assert codes == [400, 400, 429, 429]


class TestSessionsAreIndependent:
    def test_admin_survives_user_logout(self, admin_client, admin_user, user):
        admin_client.post('/api/v1/auth/login/', {'email': user.email, 'password': PASSWORD}, format='json')
        assert admin_client.get('/api/v1/auth/me/').status_code == 200
        assert admin_client.get(SESSION).json()['isAdmin'] is True
        admin_client.post('/api/v1/auth/logout/')
        assert admin_client.get('/api/v1/auth/me/').status_code == 401
        assert admin_client.get(SESSION).json()['isAdmin'] is True

    def test_user_survives_admin_logout(self, admin_client, user):
        admin_client.post('/api/v1/auth/login/', {'email': user.email, 'password': PASSWORD}, format='json')
        admin_client.post('/api/v1/admin/logout/')
        assert admin_client.get('/api/v1/auth/me/').status_code == 200

    def test_admin_survives_switching_users(self, admin_client, user, other_user):
        admin_client.post('/api/v1/auth/login/', {'email': user.email, 'password': PASSWORD}, format='json')
        admin_client.post('/api/v1/auth/login/', {'email': other_user.email, 'password': PASSWORD}, format='json')
        assert admin_client.get('/api/v1/auth/me/').json()['id'] == str(other_user.pk)
        assert admin_client.get(SESSION).json()['isAdmin'] is True


class TestReview:
    def test_pending_list_requires_admin(self, client, auth_client, submitted):
        assert client.get(PENDING).status_code == 401
        assert auth_client.get(PENDING).status_code == 401

    def test_pending_lists_only_submitted_unapproved_user_circuits(self, admin_client, user, submitted):
        Project.objects.create(owner=user, name='draft')
        Project.objects.create(owner=user, name='done', published=True, approved=True)
        Project.objects.create(name='seed', is_seed=True, published=True, approved=False, author_name='x')
        body = admin_client.get(PENDING).json()
        assert [p['name'] for p in body] == ['Submitted']
        assert body[0]['author'] == user.handle

    def test_pending_is_newest_submission_first(self, admin_client, user):
        from datetime import timedelta

        from django.utils import timezone

        now = timezone.now()
        Project.objects.create(owner=user, name='older', published=True, published_at=now - timedelta(days=2))
        Project.objects.create(owner=user, name='newer', published=True, published_at=now)
        assert [p['name'] for p in admin_client.get(PENDING).json()] == ['newer', 'older']

    def test_approve_publishes_to_gallery(self, admin_client, client, submitted):
        assert client.get('/api/v1/gallery/').json() == []
        response = admin_client.post(review(submitted.pk, 'approve'))
        assert response.status_code == 200
        assert response.json()['approved'] is True and isinstance(response.json()['approvedAt'], int)
        assert [i['name'] for i in client.get('/api/v1/gallery/').json()] == ['Submitted']
        assert admin_client.get(PENDING).json() == []

    def test_approve_is_idempotent(self, admin_client, submitted):
        first = admin_client.post(review(submitted.pk, 'approve')).json()
        second = admin_client.post(review(submitted.pk, 'approve')).json()
        assert first['approvedAt'] == second['approvedAt']

    def test_reject_returns_circuit_to_draft(self, admin_client, client, submitted):
        response = admin_client.post(review(submitted.pk, 'reject'))
        assert response.status_code == 200
        submitted.refresh_from_db()
        assert submitted.published is False and submitted.approved is False
        assert client.get('/api/v1/gallery/').json() == []
        assert admin_client.get(PENDING).json() == []

    def test_reject_takes_down_an_approved_circuit(self, admin_client, client, submitted):
        admin_client.post(review(submitted.pk, 'approve'))
        admin_client.post(review(submitted.pk, 'reject'))
        assert client.get('/api/v1/gallery/').json() == []

    def test_cannot_approve_an_unsubmitted_project(self, admin_client, user):
        draft = Project.objects.create(owner=user, name='draft')
        response = admin_client.post(review(draft.pk, 'approve'))
        assert response.status_code == 409
        draft.refresh_from_db()
        assert draft.approved is False

    def test_seeds_and_unknown_ids_are_404(self, admin_client):
        seed = Project.objects.create(name='seed', is_seed=True, published=True, approved=True)
        assert admin_client.post(review(seed.pk, 'reject')).status_code == 404
        assert admin_client.post(review(uuid.uuid4(), 'approve')).status_code == 404

    def test_regular_users_cannot_review_their_own_circuit(self, auth_client, submitted):
        assert auth_client.post(review(submitted.pk, 'approve')).status_code == 401
        submitted.refresh_from_db()
        assert submitted.approved is False

    def test_anonymous_cannot_review(self, client, submitted):
        assert client.post(review(submitted.pk, 'approve')).status_code == 401


class TestAdminCsrf:
    def test_admin_actions_enforce_csrf(self, admin_user, submitted):
        strict = APIClient(enforce_csrf_checks=True)
        assert strict.post(LOGIN, {'email': admin_user.email, 'password': PASSWORD}, format='json').status_code == 200
        assert strict.post(review(submitted.pk, 'approve')).status_code == 403
        token = strict.get('/api/v1/auth/csrf/').json()['csrfToken']
        assert strict.post(review(submitted.pk, 'approve'), HTTP_X_CSRFTOKEN=token).status_code == 200
