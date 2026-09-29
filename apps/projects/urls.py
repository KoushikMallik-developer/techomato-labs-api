from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=True)
router.include_root_view = False
router.register('projects', views.ProjectViewSet, basename='project')
router.register('folders', views.FolderViewSet, basename='folder')

urlpatterns = router.urls
