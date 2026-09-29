from unittest import mock

from django.core.cache import cache
from django.db import connection

from apps.core.tasks import enqueue_on_commit


def test_health_ok(client):
    response = client.get('/api/v1/health/')
    assert response.status_code == 200
    assert response.json() == {'status': 'ok', 'database': 'ok', 'cache': 'ok'}


def test_health_reports_unavailable_cache(client):
    with mock.patch.object(cache, 'set', side_effect=ConnectionError('redis down')):
        response = client.get('/api/v1/health/')
    assert response.status_code == 503
    body = response.json()
    assert body['status'] == 'error'
    assert body['cache'] == 'error'
    assert body['database'] == 'ok'


def test_validation_errors_use_the_uniform_shape(client):
    response = client.post('/api/v1/auth/login/', {}, format='json')
    assert response.status_code == 400
    body = response.json()
    assert body['code'] == 'validation_error'
    assert isinstance(body['detail'], str) and body['detail']
    assert 'email' in body['errors']


def test_unauthenticated_requests_get_401_with_a_message(client):
    response = client.get('/api/v1/projects/')
    assert response.status_code == 401
    assert response.json()['detail']


def test_enqueue_on_commit_runs_task_after_commit(django_capture_on_commit_callbacks):
    task = mock.Mock()
    with django_capture_on_commit_callbacks(execute=True):
        enqueue_on_commit(task, 'a', b=1)
        task.delay.assert_not_called()
    task.delay.assert_called_once_with('a', b=1)


def test_enqueue_on_commit_swallows_broker_errors(django_capture_on_commit_callbacks):
    task = mock.Mock()
    task.delay.side_effect = ConnectionError('broker down')
    with django_capture_on_commit_callbacks(execute=True):
        enqueue_on_commit(task, 'a')  # must not raise
    task.delay.assert_called_once()


def test_database_connection_is_usable():
    with connection.cursor() as cursor:
        cursor.execute('SELECT 1')
        assert cursor.fetchone()[0] == 1
