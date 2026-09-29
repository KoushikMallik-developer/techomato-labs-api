"""
Starter circuits, ported from the frontend's `lib/templates.js`.

`data/templates.json` maps a template key to a `{parts, wires, code}`
document. Loading returns a deep copy so callers can never mutate the cache.
"""
import copy
import json
from functools import lru_cache
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parent / 'data' / 'templates.json'
DEFAULT_TEMPLATE = 'blank'
STARTER_TEMPLATE = 'parking'


@lru_cache(maxsize=1)
def _load():
    with DATA_FILE.open(encoding='utf-8') as fh:
        return json.load(fh)


def template_keys():
    return list(_load().keys())


def build_template(key):
    """Return a fresh {parts, wires, code} document, or raise KeyError for an unknown key."""
    return copy.deepcopy(_load()[key])
