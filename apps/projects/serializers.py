import re

from rest_framework import serializers

from apps.core.timefields import EpochMillisField

from .models import Folder, Project
from .services import clean_parts
from .templates import DEFAULT_TEMPLATE, build_template, template_keys

DEFAULT_PROJECT_NAME = 'Untitled circuit'
DEFAULT_FOLDER_NAME = 'New folder'

MAX_PARTS = 5000
MAX_WIRES = 20000
MAX_CODE_LENGTH = 200_000
MAX_TAGS = 10
TAG_RE = re.compile(r'^[a-z0-9][a-z0-9 _-]{0,31}$')


class TagsField(serializers.ListField):
    """Lower-cased, de-duplicated tags restricted to a safe character set."""

    child = serializers.CharField()

    def __init__(self, **kwargs):
        kwargs.setdefault('required', False)
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        raw = super().to_internal_value(data)
        tags = []
        for tag in raw:
            tag = tag.strip().lower()
            if not TAG_RE.match(tag):
                raise serializers.ValidationError(
                    'Tags may use letters, numbers, spaces, "-" and "_" (up to 32 characters).'
                )
            if tag not in tags:
                tags.append(tag)
        if len(tags) > MAX_TAGS:
            raise serializers.ValidationError(f'Use at most {MAX_TAGS} tags.')
        return tags


class ObjectListField(serializers.ListField):
    """A JSON list of objects (parts / wires)."""

    child = serializers.DictField()

    def __init__(self, max_items, **kwargs):
        kwargs.setdefault('required', False)
        kwargs['max_length'] = max_items
        super().__init__(**kwargs)


class OwnedFolderField(serializers.PrimaryKeyRelatedField):
    """A folder id restricted to the requesting user's own folders."""

    def get_queryset(self):
        request = self.context.get('request')
        if request is None or not request.user.is_authenticated:
            return Folder.objects.none()
        return Folder.objects.filter(owner=request.user)


class CircuitDocumentMixin(serializers.Serializer):
    parts = ObjectListField(MAX_PARTS)
    wires = ObjectListField(MAX_WIRES)
    code = serializers.CharField(required=False, allow_blank=True, max_length=MAX_CODE_LENGTH, trim_whitespace=False)

    def validate_parts(self, value):
        return clean_parts(value)


class ProjectSerializer(CircuitDocumentMixin, serializers.ModelSerializer):
    """Owner's view of a project (and the write shape for create/update)."""

    ownerId = serializers.UUIDField(source='owner_id', read_only=True)
    name = serializers.CharField(max_length=120, required=False, allow_blank=True)
    description = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    tags = TagsField()
    folder = OwnedFolderField(required=False, allow_null=True)
    author = serializers.CharField(read_only=True)
    seed = serializers.BooleanField(source='is_seed', read_only=True)
    publishedAt = EpochMillisField(source='published_at')
    approvedAt = EpochMillisField(source='approved_at')
    createdAt = EpochMillisField(source='created_at')
    updatedAt = EpochMillisField(source='updated_at')
    # Only used on create: start from one of the built-in starter circuits.
    template = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = Project
        fields = [
            'id', 'ownerId', 'author', 'name', 'description', 'tags', 'folder', 'parts', 'wires', 'code',
            'published', 'approved', 'seed', 'publishedAt', 'approvedAt', 'createdAt', 'updatedAt', 'template',
        ]
        read_only_fields = ['id', 'published', 'approved']

    def validate_name(self, value):
        value = value.strip()
        if not value:
            if self.instance is not None:
                raise serializers.ValidationError('Name cannot be blank.')
            return DEFAULT_PROJECT_NAME
        return value

    def validate_template(self, value):
        if self.instance is not None:
            raise serializers.ValidationError('A template can only be chosen when creating a project.')
        if value and value not in template_keys():
            raise serializers.ValidationError('Unknown template.')
        return value

    def create(self, validated_data):
        key = validated_data.pop('template', '') or DEFAULT_TEMPLATE
        doc = build_template(key)
        for field in ('parts', 'wires', 'code'):
            validated_data.setdefault(field, doc[field])
        validated_data.setdefault('name', DEFAULT_PROJECT_NAME)
        return Project.objects.create(owner=self.context['request'].user, **validated_data)


class ImportSerializer(CircuitDocumentMixin):
    """Body of an exported circuit: {name, parts, wires, code}."""

    name = serializers.CharField(max_length=120, required=False, allow_blank=True)

    def validate_name(self, value):
        return value.strip() or 'Imported circuit'


class PublishSerializer(serializers.Serializer):
    description = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    tags = TagsField()


class FolderSerializer(serializers.ModelSerializer):
    ownerId = serializers.UUIDField(source='owner_id', read_only=True)
    createdAt = EpochMillisField(source='created_at')
    name = serializers.CharField(max_length=80, required=False, allow_blank=True)

    class Meta:
        model = Folder
        fields = ['id', 'ownerId', 'name', 'createdAt']
        read_only_fields = ['id']

    def validate_name(self, value):
        value = value.strip()
        if not value:
            if self.instance is not None:
                raise serializers.ValidationError('Name cannot be blank.')
            return DEFAULT_FOLDER_NAME
        return value

    def create(self, validated_data):
        validated_data.setdefault('name', DEFAULT_FOLDER_NAME)
        return Folder.objects.create(owner=self.context['request'].user, **validated_data)
