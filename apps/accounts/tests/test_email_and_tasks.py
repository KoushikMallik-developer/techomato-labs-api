import smtplib
from unittest import mock

import pytest
from django.core import mail

from apps.accounts import emails, tasks
from apps.accounts.tokens import read_reset_token, read_verification_token
from config.celery import app as celery_app


class TestEmailContent:
    def test_verification_email(self, make_user):
        user = make_user('v@example.com', name='Vera', verified=False)
        emails.send_verification_email(user)
        message = mail.outbox[0]
        assert message.subject == 'Verify your Techomato Labs email'
        assert message.to == ['v@example.com']
        assert message.from_email == 'Techomato Labs <no-reply@techomato.dev>'
        assert 'Hi Vera' in message.body
        link = [w for w in message.body.split() if w.startswith('http://frontend.test/verify-email?token=')]
        assert len(link) == 1
        assert read_verification_token(link[0].split('token=')[1]) == user

    def test_reset_email_mentions_the_expiry(self, make_user, settings):
        settings.PASSWORD_RESET_TIMEOUT = 900
        user = make_user('r@example.com', name='Rae')
        emails.send_password_reset_email(user)
        message = mail.outbox[0]
        assert 'valid for 15 minutes' in message.body
        link = [w for w in message.body.split() if 'reset-password?token=' in w][0]
        assert read_reset_token(link.split('token=')[1]) == user

    def test_link_uses_the_configured_frontend_url(self, make_user, settings):
        settings.FRONTEND_URL = 'https://techomato.com'
        emails.send_verification_email(make_user(verified=False))
        assert 'https://techomato.com/verify-email?token=' in mail.outbox[0].body

    def test_from_address_is_configurable(self, make_user, settings):
        settings.DEFAULT_FROM_EMAIL = 'Support <help@techomato.com>'
        emails.send_password_reset_email(make_user())
        assert mail.outbox[0].from_email == 'Support <help@techomato.com>'

    def test_email_bodies_never_contain_passwords_or_hashes(self, make_user):
        user = make_user(password='super-secret-pw-1', verified=False)
        emails.send_verification_email(user)
        emails.send_password_reset_email(user)
        for message in mail.outbox:
            assert 'super-secret-pw-1' not in message.body and user.password not in message.body


class TestTasks:
    def test_tasks_are_registered_with_the_celery_app(self):
        celery_app.loader.import_default_modules()
        assert 'apps.accounts.tasks.send_verification_email' in celery_app.tasks
        assert 'apps.accounts.tasks.send_password_reset_email' in celery_app.tasks

    @pytest.mark.parametrize('task', [tasks.send_verification_email, tasks.send_password_reset_email])
    def test_retry_policy_covers_mail_failures(self, task):
        assert smtplib.SMTPException in task.autoretry_for and OSError in task.autoretry_for
        assert task.max_retries == 3 and task.retry_backoff

    def test_celery_uses_django_settings(self, settings):
        assert celery_app.conf.task_always_eager is True  # test settings
        assert celery_app.conf.task_acks_late is True
        assert celery_app.conf.worker_prefetch_multiplier == 1

    def test_reset_task_sends_mail(self, make_user):
        user = make_user('t@example.com')
        tasks.send_password_reset_email(str(user.pk))
        assert [m.to for m in mail.outbox] == [['t@example.com']]

    def test_tasks_ignore_missing_users(self):
        tasks.send_password_reset_email('00000000-0000-0000-0000-000000000000')
        tasks.send_verification_email('00000000-0000-0000-0000-000000000000')
        assert mail.outbox == []

    def test_tasks_ignore_deactivated_users(self, make_user):
        user = make_user(verified=False, is_active=False)
        tasks.send_verification_email(str(user.pk))
        tasks.send_password_reset_email(str(user.pk))
        assert mail.outbox == []

    def test_verification_task_sends_for_unverified(self, make_user):
        user = make_user(verified=False)
        tasks.send_verification_email(str(user.pk))
        assert len(mail.outbox) == 1

    def test_smtp_failure_triggers_a_retry(self, make_user):
        from celery.exceptions import Retry

        user = make_user()
        with mock.patch('apps.accounts.tasks.emails.send_password_reset_email', side_effect=smtplib.SMTPAuthenticationError(535, b'nope')):
            with mock.patch.object(tasks.send_password_reset_email, 'retry', side_effect=Retry()) as retry:
                with pytest.raises(Retry):
                    tasks.send_password_reset_email.run(str(user.pk))
        assert retry.called

    def test_programming_errors_are_not_retried(self, make_user):
        user = make_user()
        with mock.patch('apps.accounts.tasks.emails.send_password_reset_email', side_effect=KeyError('bug')):
            with pytest.raises(KeyError):
                tasks.send_password_reset_email(str(user.pk))
