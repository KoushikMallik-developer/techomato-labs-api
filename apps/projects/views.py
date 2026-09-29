from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Folder, Project
from .serializers import FolderSerializer, ImportSerializer, ProjectSerializer, PublishSerializer

UUID_REGEX = r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'


def copy_project(source, owner, name):
    """A fresh, unpublished copy of `source`'s circuit owned by `owner`."""
    return Project.objects.create(
        owner=owner,
        name=name[:120],
        parts=source.parts,
        wires=source.wires,
        code=source.code,
    )


class ProjectViewSet(viewsets.ModelViewSet):
    """The signed-in user's own circuits."""

    serializer_class = ProjectSerializer
    lookup_value_regex = UUID_REGEX
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']

    def get_queryset(self):
        return Project.objects.filter(owner=self.request.user).select_related('owner')

    def _respond(self, project, http_status=status.HTTP_200_OK):
        return Response(self.get_serializer(project).data, status=http_status)

    @action(detail=True, methods=['post'])
    def duplicate(self, request, pk=None):
        source = self.get_object()
        return self._respond(copy_project(source, request.user, f'Copy of {source.name}'), status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def publish(self, request, pk=None):
        """Submit for the community gallery; an admin must approve it before it is visible."""
        project = self.get_object()
        serializer = PublishSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        project.description = serializer.validated_data.get('description', '')
        project.tags = serializer.validated_data.get('tags', [])
        project.published = True
        project.approved = False
        project.approved_at = None
        project.published_at = timezone.now()
        project.save()
        return self._respond(project)

    @action(detail=True, methods=['post'])
    def unpublish(self, request, pk=None):
        project = self.get_object()
        project.published = False
        project.approved = False
        project.approved_at = None
        project.save(update_fields=['published', 'approved', 'approved_at', 'updated_at'])
        return self._respond(project)

    @action(detail=True, methods=['get'])
    def export(self, request, pk=None):
        project = self.get_object()
        return Response({'name': project.name, 'parts': project.parts, 'wires': project.wires, 'code': project.code})

    @action(detail=False, methods=['post'], url_path='import')
    def import_project(self, request):
        serializer = ImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        project = Project.objects.create(
            owner=request.user,
            name=data.get('name') or 'Imported circuit',
            parts=data.get('parts', []),
            wires=data.get('wires', []),
            code=data.get('code', ''),
        )
        return self._respond(project, status.HTTP_201_CREATED)


class FolderViewSet(viewsets.ModelViewSet):
    serializer_class = FolderSerializer
    lookup_value_regex = UUID_REGEX
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']

    def get_queryset(self):
        return Folder.objects.filter(owner=self.request.user)
