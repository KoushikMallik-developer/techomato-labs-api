from .models import Project
from .templates import STARTER_TEMPLATE, build_template

# Transient simulator state that must never be persisted with a circuit.
TRANSIENT_PART_KEYS = ('pressed', 'triggered')


def clean_parts(parts):
    return [{k: v for k, v in part.items() if k not in TRANSIENT_PART_KEYS} for part in parts]


def create_starter_project(user):
    """The first circuit every new account gets."""
    doc = build_template(STARTER_TEMPLATE)
    return Project.objects.create(
        owner=user,
        name='My first circuit',
        parts=doc['parts'],
        wires=doc['wires'],
        code=doc['code'],
    )
