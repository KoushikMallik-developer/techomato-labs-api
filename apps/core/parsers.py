from rest_framework.exceptions import ParseError
from rest_framework.parsers import JSONParser


def contains_nul(value):
    """True if any string (or dict key) nested inside `value` holds a NUL character."""
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            if '\x00' in item:
                return True
        elif isinstance(item, dict):
            for key, child in item.items():
                if isinstance(key, str) and '\x00' in key:
                    return True
                stack.append(child)
        elif isinstance(item, list):
            stack.extend(item)
    return False


class SafeJSONParser(JSONParser):
    """
    JSON parser that refuses NUL characters. PostgreSQL cannot store them in
    text/JSON columns, so letting them through would turn a bad request into a
    500 from the database.
    """

    def parse(self, stream, media_type=None, parser_context=None):
        data = super().parse(stream, media_type, parser_context)
        if contains_nul(data):
            raise ParseError('Null characters are not allowed.')
        return data
