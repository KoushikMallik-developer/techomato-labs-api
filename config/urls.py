from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('django-admin/', admin.site.urls),
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
