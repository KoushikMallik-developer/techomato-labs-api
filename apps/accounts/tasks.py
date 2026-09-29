import smtplib

from celery import shared_task

from . import emails
from .models import User

RETRY_ON = (OSError, smtplib.SMTPException)


@shared_task(autoretry_for=RETRY_ON, retry_backoff=True, retry_kwargs={'max_retries': 3})
def send_verification_email(user_id):
    user = User.objects.filter(pk=user_id, is_active=True).first()
    # Skip if the account vanished or the address was verified in the meantime.
    if user and not user.verified:
        emails.send_verification_email(user)


@shared_task(autoretry_for=RETRY_ON, retry_backoff=True, retry_kwargs={'max_retries': 3})
def send_password_reset_email(user_id):
    user = User.objects.filter(pk=user_id, is_active=True).first()
    if user:
        emails.send_password_reset_email(user)
