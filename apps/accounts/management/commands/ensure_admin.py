from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User


class Command(BaseCommand):
    help = (
        'Create or update the admin (moderator) account from ADMIN_EMAIL / ADMIN_PASSWORD. '
        'Does nothing when they are not set.'
    )

    def handle(self, *args, **options):
        email = (settings.ADMIN_EMAIL or '').strip().lower()
        password = settings.ADMIN_PASSWORD
        if not email or not password:
            self.stdout.write('ADMIN_EMAIL/ADMIN_PASSWORD not set; skipping admin bootstrap.')
            return
        if '@' not in email:
            raise CommandError('ADMIN_EMAIL is not a valid email address.')

        user = User.objects.get_by_email(email)
        if user is None:
            User.objects.create_superuser(email, password, name=settings.ADMIN_NAME)
            self.stdout.write(self.style.SUCCESS(f'Created admin {email}.'))
            return

        changed = []
        for field in ('is_staff', 'is_superuser', 'is_active', 'verified'):
            if not getattr(user, field):
                setattr(user, field, True)
                changed.append(field)
        if not user.check_password(password):
            user.set_password(password)
            changed.append('password')
        if changed:
            user.save()
        self.stdout.write(self.style.SUCCESS(f'Admin {email} is up to date ({", ".join(changed) or "no changes"}).'))
