from django.conf import settings
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path(settings.DJANGO_ADMIN_URL, admin.site.urls),
    path(
        'api/v1/',
        include(
            [
                path('', include('apps.core.urls')),
                path('', include('apps.accounts.urls')),
                path('', include('apps.projects.urls')),
                path('', include('apps.community.urls')),
                path('', include('apps.moderation.urls')),
            ]
        ),
    ),
]

handler404 = 'apps.core.views.not_found'
handler500 = 'apps.core.views.server_error'
