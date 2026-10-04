"""git merge driver for params/*.json: merges per parameter instead of per line.

Two people publishing different parameters to the same file never conflict.
Only the same parameter changed differently on both sides is a real conflict.

    git config merge.ledger.driver "python -m ledger merge-driver %O %A %B"
    .gitattributes:  params/*.json merge=ledger
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from . import jsonfmt


def _load(p: str) -> dict:
    try:
        txt = Path(p).read_text(encoding="utf-8")
    except OSError:
        return {}
    if not txt.strip():
        return {}
    data = json.loads(txt)
    if not isinstance(data, dict):
        raise ValueError("not an object")
    return data


def merge(base: dict, ours: dict, theirs: dict) -> tuple[dict, list[str]]:
    out, conflicts = {}, []
    for k in sorted(set(base) | set(ours) | set(theirs)):
        b, o, t = base.get(k), ours.get(k), theirs.get(k)
        if o == t:
            res = o
        elif o == b:
            res = t
        elif t == b:
            res = o
        else:
            conflicts.append(k)
            res = o
        if res is not None:
            out[k] = res
    return out, conflicts


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("usage: ledger merge-driver BASE OURS THEIRS", file=sys.stderr)
        return 2
    base_p, ours_p, theirs_p = argv[:3]
    try:
        base, ours, theirs = _load(base_p), _load(ours_p), _load(theirs_p)
    except ValueError:
        return 1          # leave it to a human; git marks the file conflicted
    merged, conflicts = merge(base, ours, theirs)
    Path(ours_p).write_text(jsonfmt.dumps(merged), encoding="utf-8", newline="\n")
    if conflicts:
        print("ledger: both sides changed: " + ", ".join(conflicts), file=sys.stderr)
        return 1
    return 0
