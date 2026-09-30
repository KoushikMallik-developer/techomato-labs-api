"""Every endpoint against every kind of caller: nothing may be reachable by the wrong person."""
import uuid

import pytest

from apps.projects.models import Project
from conftest import PASSWORD

ID = str(uuid.uuid4())
API = '/api/v1/'

# (method, path) that need a signed-in *user*
USER_ONLY = [
    ('GET', 'projects/'),
    ('POST', 'projects/'),
    ('POST', 'projects/import/'),
    ('GET', f'projects/{ID}/'),
    ('PATCH', f'projects/{ID}/'),
    ('DELETE', f'projects/{ID}/'),
    ('POST', f'projects/{ID}/duplicate/'),
    ('POST', f'projects/{ID}/publish/'),
    ('POST', f'projects/{ID}/unpublish/'),
    ('GET', f'projects/{ID}/export/'),
    ('GET', 'folders/'),
    ('POST', 'folders/'),
    ('PATCH', f'folders/{ID}/'),
    ('DELETE', f'folders/{ID}/'),
    ('GET', 'auth/me/'),
    ('PATCH', 'auth/me/'),
    ('DELETE', 'auth/me/'),
    ('POST', 'auth/password/change/'),
    ('POST', 'auth/verify-email/resend/'),
    ('GET', 'following/'),
    ('PUT', 'following/somebody/'),
    ('DELETE', 'following/somebody/'),
    ('PUT', f'gallery/{ID}/like/'),
    ('DELETE', f'gallery/{ID}/like/'),
    ('POST', f'gallery/{ID}/comments/'),
    ('DELETE', f'gallery/{ID}/comments/{ID}/'),
    ('POST', f'gallery/{ID}/remix/'),
]

# (method, path) that need the *admin* session
ADMIN_ONLY = [
    ('GET', 'admin/circuits/pending/'),
    ('POST', f'admin/circuits/{ID}/approve/'),
    ('POST', f'admin/circuits/{ID}/reject/'),
]

PUBLIC = [
    ('GET', 'health/'),
    ('GET', 'gallery/'),
    ('GET', 'auth/csrf/'),
    ('GET', 'auth/oauth/providers/'),
    ('GET', 'admin/session/'),
    ('POST', 'auth/logout/'),
]


@pytest.mark.parametrize('method, path', USER_ONLY)
def test_user_endpoints_reject_anonymous_callers(client, method, path):
    response = client.generic(method, API + path, '{}', content_type='application/json')
    assert response.status_code == 401, (method, path, response.status_code)
    assert response.json()['code'] == 'not_authenticated'


@pytest.mark.parametrize('method, path', ADMIN_ONLY)
def test_admin_endpoints_reject_anonymous_callers(client, method, path):
    assert client.generic(method, API + path, '', content_type='application/json').status_code == 401


@pytest.mark.parametrize('method, path', ADMIN_ONLY)
def test_admin_endpoints_reject_regular_users(auth_client, method, path):
    assert auth_client.generic(method, API + path, '', content_type='application/json').status_code == 401


@pytest.mark.parametrize('method, path', ADMIN_ONLY)
def test_admin_endpoints_reject_users_even_if_staff_flag_is_only_set_for_the_user_session(admin_user, method, path):
    """A staff account signed in as a normal *user* still has no admin session."""
    from rest_framework.test import APIClient

    api = APIClient()
    api.post('/api/v1/auth/login/', {'email': admin_user.email, 'password': PASSWORD}, format='json')
    assert api.get('/api/v1/auth/me/').status_code == 200
    assert api.generic(method, API + path, '', content_type='application/json').status_code == 401


@pytest.mark.parametrize('method, path', PUBLIC)
def test_public_endpoints_work_anonymously(client, method, path):
    response = client.generic(method, API + path)
    assert response.status_code in (200, 204), (method, path, response.status_code)


@pytest.mark.parametrize('path', [
    'auth/signup/', 'auth/login/', 'auth/password/forgot/', 'auth/password/reset/', 'auth/verify-email/', 'admin/login/',
])
def test_credential_endpoints_only_accept_post(client, path):
    for method in ('GET', 'PUT', 'PATCH', 'DELETE'):
        assert client.generic(method, API + path).status_code == 405, (method, path)


@pytest.mark.parametrize('method', ['POST', 'PUT', 'PATCH', 'DELETE'])
def test_gallery_is_read_only(client, auth_client, method):
    assert auth_client.generic(method, API + 'gallery/', '{}', content_type='application/json').status_code == 405
    assert client.generic(method, API + f'gallery/{ID}/', '{}', content_type='application/json').status_code in (401, 405)


def test_wrong_verbs_on_owner_routes(auth_client, user):
    project = Project.objects.create(owner=user, name='p')
    for method, path in [
        ('PUT', f'projects/{project.pk}/'),
        ('GET', f'projects/{project.pk}/publish/'),
        ('GET', f'projects/{project.pk}/duplicate/'),
        ('POST', f'projects/{project.pk}/export/'),
        ('GET', 'projects/import/'),
        ('PUT', 'folders/'),
    ]:
        assert auth_client.generic(method, API + path, '{}', content_type='application/json').status_code == 405, (method, path)


def test_trailing_slash_is_required_and_does_not_leak(client):
    response = client.get('/api/v1/gallery')
    assert response.status_code in (301, 404)


@pytest.mark.parametrize('path', ['projects/', 'auth/me/', 'admin/circuits/pending/', 'auth/login/'])
def test_cors_preflight_from_the_frontend_needs_no_auth(client, settings, path):
    origin = settings.CORS_ALLOWED_ORIGINS[0]
    response = client.options(
        API + path,
        HTTP_ORIGIN=origin,
        HTTP_ACCESS_CONTROL_REQUEST_METHOD='POST',
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS='content-type,x-csrftoken',
    )
    assert response.status_code == 200
    assert response['Access-Control-Allow-Origin'] == origin
    assert response['Access-Control-Allow-Credentials'] == 'true'
    assert 'x-csrftoken' in response['Access-Control-Allow-Headers'].lower()


def test_cors_preflight_from_other_origins_gets_no_allow_header(client):
    response = client.options(
        API + 'projects/', HTTP_ORIGIN='http://evil.example', HTTP_ACCESS_CONTROL_REQUEST_METHOD='POST'
    )
    assert 'Access-Control-Allow-Origin' not in response


def test_real_responses_only_carry_cors_headers_for_allowed_origins(client, settings):
    good = client.get(API + 'gallery/', HTTP_ORIGIN=settings.CORS_ALLOWED_ORIGINS[0])
    bad = client.get(API + 'gallery/', HTTP_ORIGIN='http://evil.example')
    assert good['Access-Control-Allow-Origin'] == settings.CORS_ALLOWED_ORIGINS[0]
    assert 'Access-Control-Allow-Origin' not in bad
