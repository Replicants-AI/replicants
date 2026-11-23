"""Immutable inborn 8 by 7 body designs, using the authored anatomy."""
from copy import deepcopy
import re

MASK = ['.######.', '.######.', '.######.', '.######.', '#######.', '########', '.##..##.']
BODY_PIXELS = sum(row.count('#') for row in MASK)


def validate_design(value):
    if not isinstance(value, dict) or set(value) != {'name', 'rows', 'pal'}:
        raise ValueError('A body design has name, rows and pal.')
    if not isinstance(value['name'], str) or not 1 <= len(value['name']) <= 80:
        raise ValueError('Invalid design name.')
    rows, palette = value['rows'], value['pal']
    if not isinstance(rows, list) or len(rows) != 7 or not isinstance(palette, dict) or not 1 <= len(palette) <= BODY_PIXELS:
        raise ValueError('Use seven anatomy rows and at most one color per body pixel.')
    if any(not isinstance(k, str) or len(k) != 1 or k == '.' or not isinstance(v, str)
           or not re.fullmatch('#[0-9A-Fa-f]{6}', v) for k, v in palette.items()):
        raise ValueError('Use single-character palette keys and six-digit hex colors.')
    for y, row in enumerate(rows):
        if not isinstance(row, str) or len(row) != 8:
            raise ValueError('Use eight cells per row.')
        for x, key in enumerate(row):
            if (key == '.') != (MASK[y][x] == '.') or (key != '.' and key not in palette):
                raise ValueError('Body design must fill the anatomy exactly.')
    return deepcopy(value)
