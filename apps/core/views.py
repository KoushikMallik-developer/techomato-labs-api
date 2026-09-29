import logging

from django.core.cache import cache
from django.db import connection
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

logger = logging.getLogger(__name__)


@api_view(['GET'])
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

    healthy = all(v == 'ok' for v in checks.values())
    return Response(
        {'status': 'ok' if healthy else 'error', **checks},
        status=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
    )
