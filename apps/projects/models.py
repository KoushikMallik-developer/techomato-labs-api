import uuid

from django.conf import settings
from django.db import models


class Folder(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='folders')
    name = models.CharField(max_length=80)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return self.name


class ProjectQuerySet(models.QuerySet):
    def public(self):
        """Circuits visible in the community gallery: submitted *and* approved."""
        return self.filter(published=True, approved=True)

    def pending(self):
        """Submitted by their owner, waiting for admin review."""
        return self.filter(published=True, approved=False, is_seed=False)


class Project(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Null for the built-in gallery seeds, which belong to no account.
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name='projects'
    )
    # Display handle for seeds (real projects use owner.handle).
    author_name = models.CharField(max_length=64, blank=True, default='')
    folder = models.ForeignKey(Folder, null=True, blank=True, on_delete=models.SET_NULL, related_name='projects')

    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, default='')
    tags = models.JSONField(default=list, blank=True)
    parts = models.JSONField(default=list, blank=True)
    wires = models.JSONField(default=list, blank=True)
    code = models.TextField(blank=True, default='')

    # `published` = the owner submitted it; `approved` = an admin let it into the gallery.
    published = models.BooleanField(default=False)
    approved = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    is_seed = models.BooleanField(default=False)
    seed_likes = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProjectQuerySet.as_manager()

    class Meta:
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['owner', '-updated_at']),
            models.Index(fields=['published', 'approved']),
        ]

    def __str__(self):
        return self.name

    @property
    def author(self):
        if self.owner_id:
            return self.owner.handle
        return self.author_name or 'unknown'
