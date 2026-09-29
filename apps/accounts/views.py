import logging

from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.db import IntegrityError, transaction
from django.middleware.csrf import get_token
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.core.sessions import keep_admin_session
from apps.core.tasks import enqueue_on_commit
from apps.projects.services import create_starter_project

from . import oauth, tasks, tokens
from .models import SocialAccount, User
from .serializers import (
    ChangePasswordSerializer,
    EmailSerializer,
    LoginSerializer,
    OAuthSerializer,
    ProfileSerializer,
    ResetPasswordSerializer,
    SignupSerializer,
    TokenSerializer,
    UserSerializer,
)

logger = logging.getLogger(__name__)

PROVIDER_LABELS = {'google': 'Google', 'github': 'GitHub'}


def error(message, http_status, code='error'):
    return Response({'detail': message, 'code': code}, status=http_status)


def sign_in(request, user):
    # A user (re)login must not sign the admin out of their separate session.
    with keep_admin_session(request):
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')


class AuthView(APIView):
    """Base for credential-handling endpoints: brute-force throttled."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth'


class CsrfView(APIView):
    """Hands the SPA a CSRF token (it cannot read this domain's cookie itself)."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []

    def get(self, request):
        return Response({'csrfToken': get_token(request)})


class SignupView(AuthView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = SignupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            with transaction.atomic():
                user = User.objects.create_user(data['email'], data['password'], name=data['name'])
                create_starter_project(user)
                enqueue_on_commit(tasks.send_verification_email, str(user.pk))
        except IntegrityError:
            # Lost a race with a concurrent signup for the same email.
            return error('An account with that email already exists.', status.HTTP_400_BAD_REQUEST, 'validation_error')
        sign_in(request, user)
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


class LoginView(AuthView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email'].strip().lower()
        user = authenticate(request, username=email, password=serializer.validated_data['password'])
        if user is None:
            return error('Email or password is incorrect.', status.HTTP_400_BAD_REQUEST, 'invalid_credentials')
        sign_in(request, user)
        return Response(UserSerializer(user).data)


class LogoutView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        with keep_admin_session(request):
            logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    def get(self, request):
        return Response(UserSerializer(request.user).data)

    def patch(self, request):
        serializer = ProfileSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(UserSerializer(request.user).data)

    def delete(self, request):
        user = request.user
        with keep_admin_session(request):
            logout(request)
        user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ChangePasswordView(AuthView):
    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.user
        # Accounts created through OAuth have no password yet; let them set one.
        if user.has_usable_password() and not user.check_password(serializer.validated_data.get('current', '')):
            return error('Current password is incorrect.', status.HTTP_400_BAD_REQUEST, 'invalid_credentials')
        user.set_password(serializer.validated_data['next'])
        user.save(update_fields=['password'])
        # Other sessions are invalidated by the password change; keep this one.
        update_session_auth_hash(request, user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class VerifyEmailView(AuthView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = TokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = tokens.read_verification_token(serializer.validated_data['token'])
        if user is None:
            return error('That verification link is invalid or already used.', status.HTTP_400_BAD_REQUEST, 'invalid_token')
        if not user.verified:
            user.verified = True
            user.save(update_fields=['verified'])
        return Response(UserSerializer(user).data)


class ResendVerificationView(AuthView):
    def post(self, request):
        user = request.user
        if user.verified:
            return Response({'sent': False})
        enqueue_on_commit(tasks.send_verification_email, str(user.pk))
        return Response({'sent': True}, status=status.HTTP_202_ACCEPTED)


class ForgotPasswordView(AuthView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = EmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = User.objects.get_by_email(serializer.validated_data['email'])
        if user is not None and user.is_active:
            enqueue_on_commit(tasks.send_password_reset_email, str(user.pk))
        # Same answer either way so the endpoint cannot be used to probe for accounts.
        return Response(
            {'detail': 'If an account exists for that email, a reset link is on its way.'},
            status=status.HTTP_202_ACCEPTED,
        )


class ResetPasswordView(AuthView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = tokens.read_reset_token(serializer.validated_data['token'])
        if user is None:
            return error('That reset link is invalid or has expired.', status.HTTP_400_BAD_REQUEST, 'invalid_token')
        user.set_password(serializer.validated_data['password'])
        user.save(update_fields=['password'])
        return Response(status=status.HTTP_204_NO_CONTENT)


class OAuthProvidersView(APIView):
    """Which providers are configured (and their public client ids)."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        return Response(oauth.enabled_providers())


class OAuthLoginView(AuthView):
    permission_classes = [AllowAny]

    def post(self, request, provider):
        if provider not in PROVIDER_LABELS:
            return error('Unknown provider.', status.HTTP_404_NOT_FOUND, 'not_found')
        serializer = OAuthSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        label = PROVIDER_LABELS[provider]
        try:
            identity = oauth.fetch_identity(
                provider, serializer.validated_data['code'], serializer.validated_data['redirectUri']
            )
        except oauth.OAuthNotConfigured:
            return error(f'Sign in with {label} is not configured.', status.HTTP_503_SERVICE_UNAVAILABLE, 'oauth_disabled')
        except oauth.OAuthError:
            logger.warning('OAuth exchange failed for %s', provider, exc_info=True)
            return error(f'Could not sign in with {label}. Please try again.', status.HTTP_400_BAD_REQUEST, 'oauth_failed')

        with transaction.atomic():
            user = self._resolve_user(identity)
        if user is None:
            return error(
                f'Your {label} email address is not verified.', status.HTTP_400_BAD_REQUEST, 'oauth_failed'
            )
        if not user.is_active:
            return error('This account is disabled.', status.HTTP_403_FORBIDDEN, 'account_disabled')
        sign_in(request, user)
        return Response(UserSerializer(user).data)

    @staticmethod
    def _resolve_user(identity):
        link = SocialAccount.objects.select_related('user').filter(provider=identity.provider, uid=identity.uid).first()
        if link:
            return link.user

        if not identity.email_verified:
            return None  # never create or link an account from an unproven email
        user = User.objects.get_by_email(identity.email)
        if user is not None:
            if not user.verified:
                # The local account was never proven to belong to this address; whoever
                # registered it may not be the mailbox owner, so drop their password.
                user.set_unusable_password()
                user.verified = True
                user.save(update_fields=['password', 'verified'])
        else:
            user = User.objects.create_user(identity.email, None, name=identity.name, verified=True)
            create_starter_project(user)
        SocialAccount.objects.create(user=user, provider=identity.provider, uid=identity.uid)
        return user
