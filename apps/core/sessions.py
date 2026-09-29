"""Helpers for keeping the admin session separate from the user session."""
from contextlib import contextmanager

ADMIN_SESSION_KEY = 'techomato_admin_user_id'


@contextmanager
def keep_admin_session(request):
    """
    `login()`/`logout()` may flush the whole session. The admin sign-in lives
    in the same session under its own key and must survive user sign-in/out.
    """
    admin_id = request.session.get(ADMIN_SESSION_KEY)
    try:
        yield
    finally:
        if admin_id is not None:
            request.session[ADMIN_SESSION_KEY] = admin_id
