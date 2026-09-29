import re
import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models


def make_handle_base(name):
    base = re.sub(r'[^a-z0-9]+', '', (name or '').lower())[:16]
    return base or 'user'


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create(self, email, password, **extra):
        email = self.normalize_email(email).strip().lower()
        if not email:
            raise ValueError('An email address is required.')
        user = self.model(email=email, **extra)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault('is_staff', False)
        extra.setdefault('is_superuser', False)
        return self._create(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault('is_staff', True)
        extra.setdefault('is_superuser', True)
        extra.setdefault('verified', True)
        return self._create(email, password, **extra)

    def get_by_email(self, email):
        return self.filter(email=(email or '').strip().lower()).first()


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=120)
    # Public @handle shown on gallery items; generated once and never changes
    # so follows and links stay valid when someone renames themselves.
    handle = models.CharField(max_length=64, unique=True, editable=False)
    avatar = models.CharField(max_length=32, blank=True, default='')
    verified = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['name']

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return self.email

    def save(self, *args, **kwargs):
        self.email = (self.email or '').strip().lower()
        if not self.handle:
            self.handle = self._generate_handle()
        super().save(*args, **kwargs)

    def _generate_handle(self):
        base = make_handle_base(self.name)
        hex_id = self.id.hex
        # Start with the last 4 hex chars of the id and widen on collision.
        for size in (4, 6, 8, 12, 32):
            candidate = f'{base}_{hex_id[-size:]}'
            if not User.objects.filter(handle=candidate).exists():
                return candidate
        return f'{base}_{hex_id}'  # pragma: no cover - the full id is unique


class SocialAccount(models.Model):
    """Link between a User and an identity at an OAuth provider."""

    PROVIDERS = [('google', 'Google'), ('github', 'GitHub')]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='social_accounts')
    provider = models.CharField(max_length=20, choices=PROVIDERS)
    uid = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['provider', 'uid'], name='uniq_social_provider_uid'),
        ]

    def __str__(self):
        return f'{self.provider}:{self.uid}'
