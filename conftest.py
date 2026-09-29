import pytest
from django.core.cache import caches
from rest_framework.test import APIClient

from apps.accounts.models import User

PASSWORD = 'correct-horse-9'


@pytest.fixture(autouse=True)
def _isolate(db):
    """Every test gets the database, and empty caches/sessions/throttle counters."""
    for alias in ('default', 'sessions'):
        caches[alias].clear()
    yield
    for alias in ('default', 'sessions'):
        caches[alias].clear()


@pytest.fixture
def make_user():
    counter = {'n': 0}

    def factory(email=None, password=PASSWORD, name='Test User', **extra):
        counter['n'] += 1
        email = email or f'user{counter["n"]}@example.com'
        extra.setdefault('verified', True)
        return User.objects.create_user(email, password, name=name, **extra)

    return factory


@pytest.fixture
def user(make_user):
    return make_user('alice@example.com', name='Alice Doe')


@pytest.fixture
def other_user(make_user):
    return make_user('bob@example.com', name='Bob Roe')


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def auth_client(user):
    api = APIClient()
    api.force_login(user)
    return api


@pytest.fixture
def other_client(other_user):
    api = APIClient()
    api.force_login(other_user)
    return api


@pytest.fixture
def admin_user(make_user):
    return make_user('admin@example.com', name='Admin', is_staff=True, is_superuser=True)


@pytest.fixture
def admin_client(admin_user):
    api = APIClient()
    response = api.post('/api/v1/admin/login/', {'email': admin_user.email, 'password': PASSWORD}, format='json')
    assert response.status_code == 200, response.content
    return api


@pytest.fixture
def api_url():
    def build(path):
        return '/api/v1/' + path.lstrip('/')

    return build
