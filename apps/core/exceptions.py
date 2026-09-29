"""Uniform error bodies: {"detail": "<message>", "code": "<slug>", "errors": {...}}."""
from rest_framework import exceptions
from rest_framework.response import Response
from rest_framework.views import exception_handler


def _first_message(data):
    """Depth-first search for the first human-readable string in DRF error data."""
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        for value in data.values():
            found = _first_message(value)
            if found:
                return found
    if isinstance(data, (list, tuple)):
        for value in data:
            found = _first_message(value)
            if found:
                return found
    return None


def api_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return None

    if isinstance(exc, exceptions.ValidationError):
        detail = _first_message(response.data) or 'Invalid request.'
        body = {'detail': detail, 'code': 'validation_error'}
        if isinstance(response.data, dict):
            body['errors'] = response.data
        response.data = body
        return response

    if isinstance(response.data, dict) and 'detail' in response.data:
        response.data = {'detail': str(response.data['detail']), 'code': getattr(exc, 'default_code', 'error')}
        if isinstance(exc, exceptions.Throttled) and exc.wait is not None:
            response.data['retryAfter'] = int(exc.wait)
    return response


def error_response(message, status, code='error'):
    return Response({'detail': message, 'code': code}, status=status)
