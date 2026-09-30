"""NUL characters and unknown routes: clean 4xx responses, never a 500."""
import json

import pytest

from apps.core.parsers import contains_nul

NUL = chr(0)


@pytest.mark.parametrize(
    'payload',
    [
        {'name': 'a' + NUL + 'b'},
        {'code': NUL},
        {'parts': [{'id': 'x' + NUL}]},
        {'parts': [{'k' + NUL: 1}]},
        {'tags': ['a' + NUL]},
    ],
)
def test_nul_characters_in_json_bodies_are_rejected(auth_client, payload):
    # json.dumps escapes the control character as the six characters \u0000
    body = json.dumps(payload)
    assert '\\u0000' in body
    response = auth_client.post('/api/v1/projects/', body, content_type='application/json')
    assert response.status_code == 400
    assert response.json()['detail'] == 'Null characters are not allowed.'


def test_nul_in_anonymous_endpoints_is_a_400_too(client):
    body = json.dumps({'email': 'a' + NUL + 'b', 'password': 'x'})
    assert client.post('/api/v1/auth/login/', body, content_type='application/json').status_code == 400


def test_contains_nul_helper():
    assert contains_nul({'a': [{'b': 'x' + NUL}]})
    assert contains_nul([NUL])
    assert contains_nul({NUL: 1})
    assert not contains_nul({'a': [1, None, True, 'ok', {'b': 'fine'}]})


def test_unknown_api_routes_return_json_404(client):
    response = client.get('/api/v1/definitely-not-here/')
    assert response.status_code == 404
    assert response['Content-Type'].startswith('application/json')
    assert response.json() == {'detail': 'Not found.', 'code': 'not_found'}


def test_non_api_404_keeps_the_default_page(client):
    response = client.get('/somewhere-else/')
    assert response.status_code == 404
    assert not response['Content-Type'].startswith('application/json')
