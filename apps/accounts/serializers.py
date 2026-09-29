from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from apps.core.timefields import EpochMillisField

from .models import User


class UserSerializer(serializers.ModelSerializer):
    createdAt = EpochMillisField(source='created_at')
    providers = serializers.SerializerMethodField()
    hasPassword = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'name', 'email', 'handle', 'avatar', 'verified', 'providers', 'hasPassword', 'createdAt']
        read_only_fields = fields

    def get_providers(self, user):
        return sorted(a.provider for a in user.social_accounts.all())

    def get_hasPassword(self, user):  # noqa: N802 - camelCase is the public API shape
        return user.has_usable_password()


class TrimmedName(serializers.CharField):
    def __init__(self, **kwargs):
        kwargs.setdefault('max_length', 120)
        super().__init__(**kwargs)


class SignupSerializer(serializers.Serializer):
    name = TrimmedName(error_messages={'blank': 'Enter your name.', 'required': 'Enter your name.'})
    email = serializers.EmailField(
        max_length=254,
        error_messages={
            'blank': 'Enter an email address.',
            'required': 'Enter an email address.',
            'invalid': 'Enter a valid email address.',
        },
    )
    password = serializers.CharField(max_length=128, write_only=True, trim_whitespace=False)

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError('An account with that email already exists.')
        return value

    def validate_password(self, value):
        validate_password(value)
        return value


class LoginSerializer(serializers.Serializer):
    email = serializers.CharField()
    password = serializers.CharField(trim_whitespace=False)


class ProfileSerializer(serializers.ModelSerializer):
    name = TrimmedName(required=False)
    avatar = serializers.CharField(max_length=32, allow_blank=True, required=False)

    class Meta:
        model = User
        fields = ['name', 'avatar']


class ChangePasswordSerializer(serializers.Serializer):
    current = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)
    next = serializers.CharField(max_length=128, trim_whitespace=False)

    def validate_next(self, value):
        validate_password(value)
        return value


class EmailSerializer(serializers.Serializer):
    email = serializers.CharField()


class ResetPasswordSerializer(serializers.Serializer):
    token = serializers.CharField()
    password = serializers.CharField(max_length=128, trim_whitespace=False)

    def validate_password(self, value):
        validate_password(value)
        return value


class TokenSerializer(serializers.Serializer):
    token = serializers.CharField()


class OAuthSerializer(serializers.Serializer):
    code = serializers.CharField()
    redirectUri = serializers.CharField()
