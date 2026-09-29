from rest_framework import serializers

from apps.core.timefields import EpochMillisField
from apps.projects.models import Project

from .models import Comment


class GalleryItemSerializer(serializers.ModelSerializer):
    """Public view of an approved circuit. Expects `like_total` / `liked_by_me` annotations."""

    ownerId = serializers.UUIDField(source='owner_id', read_only=True)
    author = serializers.CharField(read_only=True)
    seed = serializers.BooleanField(source='is_seed', read_only=True)
    likeCount = serializers.IntegerField(source='like_total', read_only=True)
    liked = serializers.BooleanField(source='liked_by_me', read_only=True)
    publishedAt = EpochMillisField(source='published_at')
    createdAt = EpochMillisField(source='created_at')
    updatedAt = EpochMillisField(source='updated_at')

    class Meta:
        model = Project
        fields = [
            'id', 'ownerId', 'author', 'name', 'description', 'tags', 'parts', 'wires', 'code', 'seed',
            'likeCount', 'liked', 'publishedAt', 'createdAt', 'updatedAt',
        ]
        read_only_fields = fields


class CommentSerializer(serializers.ModelSerializer):
    userId = serializers.UUIDField(source='user_id', read_only=True)
    createdAt = EpochMillisField(source='created_at')

    class Meta:
        model = Comment
        fields = ['id', 'userId', 'name', 'text', 'createdAt']
        read_only_fields = fields


class CommentCreateSerializer(serializers.Serializer):
    text = serializers.CharField(
        max_length=2000, error_messages={'blank': 'Write something first.', 'required': 'Write something first.'}
    )
