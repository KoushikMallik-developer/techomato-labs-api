"""Uniform error bodies: {"detail": "<message>", "code": "<slug>", "errors": {...}}."""
import math

from django.core.exceptions import PermissionDenied
from django.http import Http404
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


def _code_for(exc):
    # DRF converts these Django exceptions to API errors but hands us the original.
    if isinstance(exc, Http404):
        return 'not_found'
    if isinstance(exc, PermissionDenied):
        return 'permission_denied'
    return getattr(exc, 'default_code', 'error')


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
        response.data = {'detail': str(response.data['detail']), 'code': _code_for(exc)}
        if isinstance(exc, exceptions.Throttled) and exc.wait is not None:
            # Round up: retrying at the truncated value would still be throttled.
            response.data['retryAfter'] = math.ceil(exc.wait)
    return response


def error_response(message, status, code='error'):
    return Response({'detail': message, 'code': code}, status=status)
