from django.contrib import admin

from .models import Folder, Project


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'owner', 'published', 'approved', 'is_seed', 'updated_at')
    list_filter = ('published', 'approved', 'is_seed')
    search_fields = ('name', 'owner__email', 'owner__handle')
    raw_id_fields = ('owner', 'folder')


@admin.register(Folder)
class FolderAdmin(admin.ModelAdmin):
    list_display = ('name', 'owner', 'created_at')
    raw_id_fields = ('owner',)
