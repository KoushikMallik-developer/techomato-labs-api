from django.core.exceptions import ValidationError
from rest_framework.authentication import SessionAuthentication

from apps.accounts.models import User
from apps.core.sessions import ADMIN_SESSION_KEY


class AdminSessionAuthentication(SessionAuthentication):
    """
    Authenticates the *admin* sign-in, which is stored in the session under its
    own key so it stays independent from the regular user sign-in. Like
    SessionAuthentication it enforces CSRF for every authenticated request.
    """

    def authenticate(self, request):
        admin_id = request._request.session.get(ADMIN_SESSION_KEY)
        if not admin_id:
            return None
        try:
            user = User.objects.filter(pk=admin_id, is_active=True, is_staff=True).first()
        except (ValidationError, ValueError, TypeError):
            user = None
        if user is None:
            return None
        self.enforce_csrf(request)
        return (user, None)

    def authenticate_header(self, request):
        return 'Session'
