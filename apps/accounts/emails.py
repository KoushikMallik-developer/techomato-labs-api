from django.conf import settings
from django.core.mail import send_mail

from .tokens import make_reset_token, make_verification_token


def _link(path, token):
    # The SPA uses BrowserRouter, so routes are plain paths (no '#').
    return f'{settings.FRONTEND_URL}/{path}?token={token}'


def send_verification_email(user):
    link = _link('verify-email', make_verification_token(user))
    send_mail(
        subject='Verify your Techomato Labs email',
        message=(
            f'Hi {user.name},\n\n'
            f'Confirm your email address to finish setting up your account:\n{link}\n\n'
            'If you did not create an account, you can ignore this message.'
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
    )


def send_password_reset_email(user):
    link = _link('reset-password', make_reset_token(user))
    minutes = max(1, settings.PASSWORD_RESET_TIMEOUT // 60)
    send_mail(
        subject='Reset your Techomato Labs password',
        message=(
            f'Hi {user.name},\n\n'
            f'Use this link to choose a new password (valid for {minutes} minutes):\n{link}\n\n'
            'If you did not ask for this, you can ignore this message.'
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
    )
