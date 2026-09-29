from django.contrib.auth import authenticate
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts.serializers import LoginSerializer
from apps.core.sessions import ADMIN_SESSION_KEY
from apps.projects.models import Project
from apps.projects.serializers import ProjectSerializer

from .authentication import AdminSessionAuthentication


class AdminAPIView(APIView):
    authentication_classes = [AdminSessionAuthentication]
    permission_classes = [IsAuthenticated]


class AdminLoginView(APIView):
    """Admin sign-in (no signup: accounts are created with `manage.py ensure_admin`)."""

    authentication_classes = [AdminSessionAuthentication]
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth'

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email'].strip().lower()
        user = authenticate(request, username=email, password=serializer.validated_data['password'])
        if user is None or not user.is_staff:
            return Response(
                {'detail': 'Invalid admin email or password.', 'code': 'invalid_credentials'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        request.session.cycle_key()
        request.session[ADMIN_SESSION_KEY] = str(user.pk)
        return Response({'email': user.email})


class AdminLogoutView(APIView):
    authentication_classes = [AdminSessionAuthentication]
    permission_classes = [AllowAny]

    def post(self, request):
        request.session.pop(ADMIN_SESSION_KEY, None)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AdminSessionView(APIView):
    """Whether the current browser session is signed in as admin."""

    authentication_classes = [AdminSessionAuthentication]
    permission_classes = [AllowAny]

    def get(self, request):
        signed_in = bool(request.user and request.user.is_authenticated)
        return Response({'isAdmin': signed_in, 'email': request.user.email if signed_in else None})


class PendingCircuitsView(AdminAPIView):
    def get(self, request):
        pending = Project.objects.pending().select_related('owner').order_by('-published_at')
        return Response(ProjectSerializer(pending, many=True, context={'request': request}).data)


class ReviewView(AdminAPIView):
    """Shared plumbing for approve / reject."""

    def _project(self, pk):
        return get_object_or_404(Project.objects.select_related('owner'), pk=pk, is_seed=False)

    def _respond(self, request, project):
        return Response(ProjectSerializer(project, context={'request': request}).data)


class ApproveCircuitView(ReviewView):
    def post(self, request, pk):
        project = self._project(pk)
        if not project.published:
            return Response(
                {'detail': 'That circuit has not been submitted for review.', 'code': 'not_submitted'},
                status=status.HTTP_409_CONFLICT,
            )
        if not project.approved:
            project.approved = True
            project.approved_at = timezone.now()
            project.save(update_fields=['approved', 'approved_at', 'updated_at'])
        return self._respond(request, project)


class RejectCircuitView(ReviewView):
    def post(self, request, pk):
        project = self._project(pk)
        project.published = False
        project.approved = False
        project.approved_at = None
        project.save(update_fields=['published', 'approved', 'approved_at', 'updated_at'])
        return self._respond(request, project)
