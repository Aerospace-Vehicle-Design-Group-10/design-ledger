"""reading and writng params/<discipline>.json"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
from pathlib import Path

from . import jsonfmt
from .config import LedgerError

# "verified" is either UNVERIFIED or a dict saying who checked which value, and when.
# a verification only counts while the value (and units) still match what was checked.
UNVERIFIED = "-"


def verification_holds(rec: dict) -> bool:
    v = rec.get("verified", UNVERIFIED)
    return (
        isinstance(v, dict)
        and values_equal(v.get("value"), rec.get("value"))
        and v.get("units") == rec.get("units")
    )


# ensures variable names start with a letter (can have digits, or underscores after)
# capped at 63 characters
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,62}$")

# statuses for what we did to get different values
STATUSES = (
    "requirement",
    "assumed",
    "computed",
)


# last digits can always have noise (if they are floats)
def values_equal(a, b, rel: float = 1e-9) -> bool:
    # bools are easy
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b or a == b

    # said tolerance check if int or float
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if a == b:
            return True
        return math.isclose(float(a), float(b), rel_tol=rel, abs_tol=0.0)

    # elementwise list comparison has the same issue so we do the tolerance equality here as well
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(values_equal(x, y, rel) for x, y in zip(a, b))
    return a == b


# turns numpy scalars/arrays and tuples into plain JSON types
# others are rejected
def normalise_value(v):
    # strings are handled seperately and bytes we don't use but both have this method
    if hasattr(v, "tolist") and not isinstance(v, (str, bytes)):
        v = v.tolist()

    if isinstance(v, tuple):
        v = list(v)

    if v is None:
        raise LedgerError("value is empty (None/NaN). give real numbers")

    if isinstance(v, (bool, str, int, float)):  #  checks numbers aren't inf
        return _scalar(v)

    if isinstance(
        v, list
    ):  # if the element is a list we can just recurse, otherwise do the scalar check
        if len(v) == 1 and not isinstance(v[0], list):  # for matlab 1x1 arrays
            return normalise_value(v[0])
        return [normalise_value(e) if isinstance(e, list) else _scalar(e) for e in v]

    raise LedgerError(
        f"couldn't store element of type {type(v).__name__}. use strings, numbers, bools or lists"
    )


def _scalar(e):
    if hasattr(e, "item"):  # if its a numpy scalar we need the python value
        e = e.item()
    if isinstance(e, (bool, int, float, str)):
        if isinstance(e, float) and not math.isfinite(e):
            raise LedgerError(f"value {e!r} isn't finite (how'd you do this)")
        return e
    raise LedgerError(f"couldn't store element of type {type(e).__name__}")


class Registry:
    """all the parameters grouped by discipline file"""

    files: dict[str, dict]
    load_errors: list[str]

    def __init__(self, files: dict[str, dict], errors: list[str] | None = None):
        self.files = files
        self.load_errors = errors or []

    # loads all the params from the params directory into one registry
    @classmethod
    def load(cls, params_dir: Path) -> "Registry":
        files, errors = {}, []

        if params_dir.is_dir():  # sad i need to guard this xD
            # basically for all json files in the directory, load to files,
            # and append the errors (if any)
            for p in sorted(params_dir.glob("*.json")):
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))

                    if not isinstance(data, dict):
                        raise ValueError("top level must be an object")

                    files[p.stem] = data
                except ValueError as e:
                    errors.append(f"{p.name} doesn't contain valid json ({e})")
            return cls(files, errors)
        else:
            raise LedgerError("params_dir isn't a directory")

    # loads the registry as it was at a git ref (which we can use to compare a PR w main)
    @classmethod
    def load_at_ref(cls, root: Path, params_rel: str, ref: str) -> "Registry":
        try:
            # this lists the filenames that existed in the params directory at the given ref
            # params_rel is relative as git needs the path relative to the repo root
            out = subprocess.run(
                ["git", "ls-tree", "--name-only", f"{ref}:{params_rel}"],
                cwd=root,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.split()
        except subprocess.CalledProcessError:
            return cls({})

        files = {}
        for name in out:
            # ignore non json files
            if not name.endswith(".json"):
                continue

            try:
                # gets the file contents at the commit ref
                txt = subprocess.run(
                    ["git", "show", f"{ref}:{params_rel}/{name}"],
                    cwd=root,
                    capture_output=True,
                    text=True,
                    check=True,
                    encoding="utf-8",
                ).stdout
                # we strip the .json so we are just left with the filename
                files[name[:-5]] = json.loads(txt)
            except (subprocess.CalledProcessError, ValueError):
                pass

        # files is a dict keyed by the discipline and each entry is the
        # dict that was loaded from the json
        return cls(files)

    @property
    def records(self) -> dict[str, dict]:
        # we want to flatten the different disciplines into one big dict
        out = {}
        for discipline in sorted(self.files):
            for name, rec in self.files[discipline].items():
                # takes whats in each discipline dict
                # and puts it in out
                out.setdefault(name, rec)
        return out

    # returns the discipline a variable belongs to
    def discipline_of(self, name: str) -> str | None:
        for discipline in sorted(self.files):
            if name in self.files[discipline]:
                return discipline

    # finds every parameter name that appears in more than one discipline file
    def duplicates(self) -> dict[str, list[str]]:
        seen: dict[str, list[str]] = {}  # maps "param_name" to [disciplines its in]

        for discipline, recs in self.files.items():
            for name in recs:
                seen.setdefault(name, []).append(discipline)
        return {
            name: dupe_list for name, dupe_list in seen.items() if len(dupe_list) > 1
        }

    # checks if the parameter name is in any of the disciplines
    def __contains__(self, name):
        return self.discipline_of(name) is not None

    # gets a parameter from the data
    def get(self, name: str) -> dict:
        discipline = self.discipline_of(name)
        if discipline is None:
            raise KeyError(name)
        return self.files[discipline][name]

    # writes `record` to the `parameter` in the defined `discipline`
    def set(self, discipline: str, name: str, record: dict):
        self.files.setdefault(discipline, {})[name] = record

    # saves the current state for a given discipline to the corresponding json file
    def save(self, params_dir: Path, discipline: str):
        params_dir.mkdir(parents=True, exist_ok=True)
        path = params_dir / f"{discipline}.json"

        text = jsonfmt.dumps(dict(sorted(self.files.get(discipline, {}).items())))

        tmp = path.with_suffix(".json_tmp")
        tmp.write_text(text, encoding="utf-8", newline="\n")

        os.replace(tmp, path)
