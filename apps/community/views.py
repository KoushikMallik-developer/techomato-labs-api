import re

from django.db import IntegrityError
from django.db.models import BooleanField, Count, Exists, F, OuterRef, Q, Value
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.projects.models import Project
from apps.projects.serializers import ProjectSerializer
from apps.projects.views import copy_project

from .models import Comment, Follow, Like
from .serializers import CommentCreateSerializer, CommentSerializer, GalleryItemSerializer

FOLLOWING_FILTER = '__following__'
HANDLE_RE = re.compile(r'^[A-Za-z0-9_]{1,64}$')


def error(message, http_status, code='error'):
    return Response({'detail': message, 'code': code}, status=http_status)


def gallery_queryset(user):
    """Approved circuits annotated with their like total and whether `user` liked them."""
    if user is not None and user.is_authenticated:
        liked = Exists(Like.objects.filter(project=OuterRef('pk'), user=user))
    else:
        liked = Value(False, output_field=BooleanField())
    return (
        Project.objects.public()
        .select_related('owner')
        .annotate(like_total=F('seed_likes') + Count('likes', distinct=True), liked_by_me=liked)
    )


def like_total(project):
    return project.seed_likes + Like.objects.filter(project=project).count()


class GalleryListView(ListAPIView):
    """Community circuits. Query: q (search), tag, author (handle), sort=popular|new."""

    permission_classes = [AllowAny]
    serializer_class = GalleryItemSerializer

    def get_queryset(self):
        params = self.request.query_params
        user = self.request.user
        qs = gallery_queryset(user)

        q = params.get('q', '').strip()
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q) | Q(tags__icontains=q))

        tag = params.get('tag', '').strip()
        if tag == FOLLOWING_FILTER:
            handles = list(Follow.objects.filter(follower=user).values_list('handle', flat=True)) if user.is_authenticated else []
            qs = qs.filter(Q(owner__handle__in=handles) | Q(author_name__in=handles))
        elif tag:
            # Tags are stored as a JSON list of plain ASCII strings, so a quoted
            # match is an exact element match.
            qs = qs.filter(tags__icontains=f'"{tag.lower()}"')

        author = params.get('author', '').strip()
        if author:
            qs = qs.filter(Q(owner__handle=author) | Q(author_name=author))

        if params.get('sort') == 'new':
            return qs.order_by(F('published_at').desc(nulls_last=True), 'id')
        return qs.order_by('-like_total', F('published_at').desc(nulls_last=True), 'id')


class GalleryDetailView(RetrieveAPIView):
    permission_classes = [AllowAny]
    serializer_class = GalleryItemSerializer

    def get_queryset(self):
        return gallery_queryset(self.request.user)


class LikeView(APIView):
    """PUT = like, DELETE = unlike. Both are idempotent."""

    def _project(self, pk):
        return get_object_or_404(Project.objects.public(), pk=pk)

    def put(self, request, pk):
        project = self._project(pk)
        try:
            Like.objects.get_or_create(user=request.user, project=project)
        except IntegrityError:
            pass  # a concurrent identical request already created it
        return Response({'liked': True, 'likeCount': like_total(project)})

    def delete(self, request, pk):
        project = self._project(pk)
        Like.objects.filter(user=request.user, project=project).delete()
        return Response({'liked': False, 'likeCount': like_total(project)})


class CommentListCreateView(APIView):
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get(self, request, pk):
        project = get_object_or_404(Project.objects.public(), pk=pk)
        return Response(CommentSerializer(project.comments.all(), many=True).data)

    def post(self, request, pk):
        project = get_object_or_404(Project.objects.public(), pk=pk)
        serializer = CommentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        comment = Comment.objects.create(
            project=project, user=request.user, name=request.user.name, text=serializer.validated_data['text']
        )
        return Response(CommentSerializer(comment).data, status=status.HTTP_201_CREATED)


class CommentDeleteView(APIView):
    """People can only delete their own comments."""

    def delete(self, request, pk, comment_id):
        comment = get_object_or_404(Comment, pk=comment_id, project_id=pk, user=request.user)
        comment.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class RemixView(APIView):
    """Copy a community circuit into the signed-in user's own projects."""

    def post(self, request, pk):
        source = get_object_or_404(Project.objects.public(), pk=pk)
        copy = copy_project(source, request.user, f'{source.name} (remix)')
        return Response(ProjectSerializer(copy, context={'request': request}).data, status=status.HTTP_201_CREATED)


class FollowingView(APIView):
    """Handles of the authors the current user follows."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(list(Follow.objects.filter(follower=request.user).values_list('handle', flat=True)))


class FollowView(APIView):
    """PUT = follow, DELETE = unfollow. Both are idempotent."""

    def _handle(self, handle):
        return handle if HANDLE_RE.match(handle) else None

    def put(self, request, handle):
        if not self._handle(handle):
            return error('Invalid author handle.', status.HTTP_400_BAD_REQUEST, 'validation_error')
        if handle == request.user.handle:
            return error('You cannot follow yourself.', status.HTTP_400_BAD_REQUEST, 'validation_error')
        try:
            Follow.objects.get_or_create(follower=request.user, handle=handle)
        except IntegrityError:
            pass
        return Response({'handle': handle, 'following': True})

    def delete(self, request, handle):
        Follow.objects.filter(follower=request.user, handle=handle).delete()
        return Response({'handle': handle, 'following': False})
