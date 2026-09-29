from django.contrib import admin

from .models import SocialAccount, User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('email', 'name', 'handle', 'verified', 'is_active', 'is_staff', 'created_at')
    list_filter = ('verified', 'is_active', 'is_staff')
    search_fields = ('email', 'name', 'handle')
    readonly_fields = ('handle', 'created_at', 'last_login', 'password')
    exclude = ('groups', 'user_permissions')


@admin.register(SocialAccount)
class SocialAccountAdmin(admin.ModelAdmin):
    list_display = ('user', 'provider', 'uid', 'created_at')
    list_filter = ('provider',)
