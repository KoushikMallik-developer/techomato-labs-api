from rest_framework.authentication import SessionAuthentication


class ApiSessionAuthentication(SessionAuthentication):
    """
    Session cookie auth (with CSRF enforcement for signed-in users) that
    answers 401 instead of DRF's default 403 when nobody is signed in, so the
    SPA can tell "log in first" apart from "you may not do that".
    """

    def authenticate_header(self, request):
        return 'Session'
