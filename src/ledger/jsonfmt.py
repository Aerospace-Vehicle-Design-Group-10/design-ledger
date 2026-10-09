"""
JSON formatting for the registry files

cuz we hash every write needs to go through dump so a file only changes when a value does.
we can keep the record keys with a fixed order

"""

from __future__ import annotations

import json
import math

# the base field order for everything
RECORD_ORDER: list[str] = [
    "value",
    "units",
    "status",
    "verified",
    "desc",
    "note",
    "frozen",
    "unfrozen",
    "source",
    "inputs",
    "by",
    "updated",
]


# simple number formatting
def fmt_number(x) -> str:
    if isinstance(x, bool):
        return "true" if x else "false"
    if isinstance(x, int):
        return str(x)
    x = float(x)
    if not math.isfinite(x):
        raise ValueError(f"cannot store non-finite number {x!r}")
    if x.is_integer() and abs(x) < 1e15:
        return str(int(x))
    for p in (15, 16, 17):
        s = "%.*g" % (p, x)
        if float(s) == x:
            return s
    return repr(x)


# orders the inputted dict so that the fields in RECORD_ORDER come first, then the rest
def _key_order(d: dict, record_level: bool):
    if not record_level:
        return sorted(d)
    known = [k for k in RECORD_ORDER if k in d]  # the ones we defined
    rest = sorted(k for k in d if k not in RECORD_ORDER)  # the others
    return rest + known


# is the list flat (crazy)
def _is_flat_list(v) -> bool:
    return isinstance(v, list) and all(not isinstance(e, (dict, list)) for e in v)


# custom serialization
def _dump(v, indent: int, depth: int) -> str:
    # pad is the indent for the children of the current container
    pad = " " * indent * (depth + 1)
    # indent for the closing ] or } for the current container
    end = " " * indent * depth

    if v is None:
        return "null"
    if isinstance(v, (bool, int, float)):
        return fmt_number(v)  # ensures numbers get checked and have the right format
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)  # handles any quotes and escapes

    # lists need more care
    if isinstance(v, list):
        if not v:  # just an empty list
            return "[]"
        if _is_flat_list(v):  # if the list is flat we just display it as [...,]
            # run through dump again because of the above if's
            return "[" + ", ".join(_dump(e, indent, depth + 1) for e in v) + "]"

        # if its not, we go one element per line, indented
        inner = ",\n".join(pad + _dump(e, indent, depth + 1) for e in v)
        return "[\n" + inner + "\n" + end + "]"

    # dicts are similar to lists
    if isinstance(v, dict):
        if not v:  # again just empty dict
            return "{}"
        # because of the formatting, depth 1 is a parameter record (file -> name -> record)
        keys = _key_order(v, record_level=(depth == 1))

        inner = ",\n".join(
            pad
            + json.dumps(str(k), ensure_ascii=False)
            + ": "
            + _dump(v[k], indent, depth + 1)
            for k in keys
        )
        return "{\n" + inner + "\n" + end + "}"
    raise TypeError(f"cannot store value of type {type(v).__name__}")


def dumps(obj, indent: int = 2) -> str:
    return _dump(obj, indent, 0) + "\n"
