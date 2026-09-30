import logging

from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse
from django.views import defaults
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework.throttling import BaseThrottle

logger = logging.getLogger(__name__)


@api_view(['GET', 'HEAD'])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([])
def health(request):
    """Liveness/readiness probe: verifies PostgreSQL and Redis are reachable."""
    checks = {}
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
        checks['database'] = 'ok'
    except Exception:  # noqa: BLE001
        logger.exception('Health check: database unreachable')
        checks['database'] = 'error'
    try:
        cache.set('health-check', '1', 5)
        checks['cache'] = 'ok' if cache.get('health-check') == '1' else 'error'
    except Exception:  # noqa: BLE001
        logger.exception('Health check: cache unreachable')
        checks['cache'] = 'error'

    body = {}
    if request.query_params.get('debug') == 'ip':
        # Echoes the caller's own address details so an operator can confirm
        # THROTTLE_NUM_PROXIES against their hosting platform's proxy chain.
        body['client'] = {
            'ident': BaseThrottle().get_ident(request),
            'remoteAddr': request.META.get('REMOTE_ADDR'),
            'xForwardedFor': request.META.get('HTTP_X_FORWARDED_FOR'),
            'numProxies': api_settings.NUM_PROXIES,
        }

    healthy = all(v == 'ok' for v in checks.values())
    return Response(
        {'status': 'ok' if healthy else 'error', **checks, **body},
        status=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
    )


def not_found(request, exception=None):
    """404 handler: JSON under /api/, Django's stock page elsewhere."""
    if request.path.startswith('/api/'):
        return JsonResponse({'detail': 'Not found.', 'code': 'not_found'}, status=404)
    return defaults.page_not_found(request, exception)


def server_error(request):
    """500 handler: JSON under /api/, Django's stock page elsewhere."""
    if request.path.startswith('/api/'):
        return JsonResponse({'detail': 'Something went wrong on our side.', 'code': 'server_error'}, status=500)
    return defaults.server_error(request)
