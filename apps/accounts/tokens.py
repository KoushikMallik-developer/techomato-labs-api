"""Stateless, expiring tokens for email verification and password reset."""
from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core import signing
from django.core.exceptions import ValidationError
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from .models import User

VERIFY_SALT = 'techomato.accounts.verify-email'


def make_verification_token(user):
    # The email is part of the payload, so changing it invalidates old links.
    return signing.dumps({'uid': str(user.pk), 'email': user.email}, salt=VERIFY_SALT)


def read_verification_token(token):
    """Return the matching User, or None if the token is bad/expired/stale."""
    try:
        data = signing.loads(token, salt=VERIFY_SALT, max_age=settings.EMAIL_VERIFICATION_MAX_AGE)
        return User.objects.filter(pk=data['uid'], email=data['email'], is_active=True).first()
    except (signing.BadSignature, ValidationError, KeyError, TypeError, ValueError):
        return None


def make_reset_token(user):
    uid = urlsafe_base64_encode(force_bytes(str(user.pk)))
    return f'{uid}.{default_token_generator.make_token(user)}'


def read_reset_token(token):
    """Return the matching User, or None if the token is bad/expired/already used."""
    try:
        uid, _, raw = (token or '').partition('.')
        if not uid or not raw:
            return None
        user = User.objects.filter(pk=force_str(urlsafe_base64_decode(uid)), is_active=True).first()
    except (ValidationError, TypeError, ValueError, OverflowError, UnicodeDecodeError):
        return None
    if user is None or not default_token_generator.check_token(user, raw):
        return None
    return user
