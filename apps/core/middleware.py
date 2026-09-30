
HEALTH_PATH = '/api/v1/health/'


class HealthCheckMiddleware:
    """
    Answers the health probe before host validation.

    Platform health checks (Render, load balancers, orchestrators) often call
    the container by IP or an internal name that is not in ALLOWED_HOSTS, which
    would make Django reject them with a 400 and mark a healthy service down.
    The endpoint only reports database/cache status, which is not sensitive.
    Every other path still goes through normal host validation.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == HEALTH_PATH and request.method in ('GET', 'HEAD'):
            from .views import health

            response = health(request)
            response.render()
            return response
        return self.get_response(request)
