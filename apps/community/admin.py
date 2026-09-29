from django.contrib import admin

from .models import Comment, Follow, Like


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ('name', 'project', 'created_at')
    raw_id_fields = ('project', 'user')


admin.site.register(Like)
admin.site.register(Follow)
