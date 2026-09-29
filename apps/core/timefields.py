from rest_framework import serializers


def to_millis(dt):
    """datetime -> epoch milliseconds (what the frontend's Date.now() logic expects)."""
    return int(dt.timestamp() * 1000) if dt else None


class EpochMillisField(serializers.Field):
    """Read-only datetime rendered as integer epoch milliseconds."""

    def __init__(self, **kwargs):
        kwargs['read_only'] = True
        super().__init__(**kwargs)

    def to_representation(self, value):
        return to_millis(value)
