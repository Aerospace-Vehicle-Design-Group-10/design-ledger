"""the calls the analysis scripts will use, so eg. get, publish etc."""

from __future__ import annotations

import contextlib
import datetime as _dt
import difflib
import os
from pathlib import Path

from . import provenance
from .config import Config, LedgerError, find_root
from .registry import (
    NAME_RE,
    UNVERIFIED,
    Registry,
    normalise_value,
    values_equal,
    verification_holds,
)

### --- state --- ###
_reads: list[dict] = [{}]  # stack of read logs
_overrides: list[dict] = []  # stack of what-if parameters/new parameters
_cache: dict = {}  # root (mtimes, Registry)
_roots: dict = {}  # start dir -> root
_configs: dict = {}  # root -> (mtime, config)


# gets the root
def _root(start=None) -> Path:
    start = start or provenance.caller_file()

    # find root falls back to cwd/env so the cache key needs all three otherwise if one changes we might miss it and fail to invalidate the cache
    key = (
        str(Path(start).parent) if start else None,
        str(Path.cwd()),
        os.environ.get("LEDGER_ROOT"),
    )
    # we cache so that we avoid going through the filesystem on every get/publish
    if key not in _roots:
        _roots[key] = find_root(start)
    return _roots[key]


# gets/creates the config
def _config(root: Path) -> Config:
    # we need to check modification time so edits to ledger.json invalidate the cache

    mtime = (root / "ledger.json").stat().st_mtime_ns
    hit = _configs.get(root)
    if hit and hit[0] == mtime:
        return hit[1]

    cfg = Config.load(root)
    _configs[root] = (mtime, cfg)
    return cfg


# gets/creates the registry
def _registry(cfg: Config) -> Registry:
    pdir = cfg.params_dir

    # snapshot (name, mtime) per file sso that an edit, add or removal of any params file invalidates the cache
    mtimes = (
        tuple(sorted((p.name, p.stat().st_mtime_ns) for p in pdir.glob("*.json")))
        if pdir.is_dir()
        else ()
    )

    hit = _cache.get(cfg.root)
    if hit and hit[0] == mtimes:
        return hit[1]

    reg = Registry.load(pdir)
    # incase we end up w errors
    if reg.load_errors:
        raise LedgerError(
            "some registry files are broken:\n  " + "\n  ".join(reg.load_errors)
        )
    _cache[cfg.root] = (mtimes, reg)
    return reg


# fuzzy incase variable names are misspelled etc.
def _missing(name: str, reg: Registry) -> LedgerError:
    close = difflib.get_close_matches(name, list(reg.records), n=3, cutoff=0.6)
    hint = f" did you mean {', '.join(close)}" if close else ""
    return LedgerError(f"'{name}' isn't in the registry yet {hint}")


### --- reading --- ###
# reading is remembered so it becomes an input of whatever this run ends up publishing
def get(name: str):
    # if its a non-published user value
    for ov in reversed(_overrides):
        if name in ov:
            return ov[name]

    cfg = _config(_root())
    reg = _registry(cfg)

    # fuzzy hints for if somethings misspelled
    if name not in reg:
        raise _missing(name, reg)

    value = reg.get(name)["value"]
    _reads[-1][name] = value  # stick it at the end
    return value


# the full record (value, units, source, inputs ...)
# isn't logged as a read
def record(name: str) -> dict:
    cfg = _config(_root())
    reg = _registry(cfg)
    if name not in reg:
        raise _missing(name, reg)
    return dict(reg.get(name))


# what a publish call right now would record in it's inputs field
def reads() -> dict:
    return dict(_reads[-1])


# forgets everything read so far (eg if calculating unrelated values so the input stays clean)
def begin():
    # empty every level but keep the stack's depth, so an open step() block can still
    # pop its own level on exit (replacing the stack here used to crash that pop)
    for log in _reads:
        log.clear()


# reads inside a block are the only inputs of values published inside that block
# so eg:
# with ledger.step():
#   W0 = ledger.get("MTOW")
#   ledger.publish("CG_x", x, units="m")
@contextlib.contextmanager
def step():
    _reads.append({})
    try:
        yield
    finally:
        inner = _reads.pop()
        _reads[-1].update(inner)


# what-if values for get, letting you modify whatever you need
# no publishing is allowed while this is active
# eg:
# with ledger.override(wing_AR=10):
#   run_sizing()
@contextlib.contextmanager
def override(**values):
    _overrides.append(values)
    try:
        yield
    finally:
        _overrides.pop()


# override for override (lol mouthfull)
def ov(values):
    override(**values)


### --- writing --- ###
# writes a value to the local copy of the registry with the inputs the run read
# and a fingerprint of the script that computed the value
# inputs and discipline are usually inferred but can be overrided manually
def publish(
    name: str,
    value,
    units: str,
    *,
    note: str | None = None,
    desc: str | None = None,
    reference: str | None = None,
    inputs: list[str] | None = None,
    discipline: str | None = None,
) -> dict:
    if _overrides:
        raise LedgerError(
            "can't publish inside ledger.override(), you can't use manually edited values"
        )

    # we need the script that is trying to publish the number
    script = provenance.caller_file()
    root = _root(script)
    return publish_with(
        root,
        name,
        value,
        units,
        note=note,
        desc=desc,
        reference=reference,
        inputs=inputs,
        discipline=discipline,
        script=script,
        read_log=reads(),
    )


# publishes (or re-publishes) a parameter.
# validates it, works out which discipline it's in, records what it was computed from,
# and writes the record to disc (unless nothing changed)
def publish_with(
    root: Path,
    name,
    value,
    units,
    *,
    note=None,
    desc=None,
    reference=None,
    inputs=None,
    discipline=None,
    script: Path | None,
    read_log: dict,
    by: str | None = None,
    status: str | None = None,
    quiet: bool = False,
) -> dict:
    cfg = _config(root)
    reg = _registry(cfg)

    if not isinstance(name, str) or not NAME_RE.match(name):
        raise LedgerError(
            f"'{name}' is not a valid name. needs to start w a letter, after only letters, digits, and _ allowed (max 63 chars)"
        )
    if not isinstance(units, str) or not units.strip():
        raise LedgerError(f"'{name}' units are required (use '-' if it's dimensionless")

    value = normalise_value(value)

    old = reg.get(name) if name in reg else None
    # frozen params can only move via the explicit unfreeze command, so a reason always ends up in the PR/review
    if old and old.get("frozen"):
        raise LedgerError(
            f'"{name}" is frozen at "{old["frozen"]}".'
            f'if it needs to change, run `ledger unfreeze {name} --reason "..."` and say why in the pr'
        )

    # which file
    disc = reg.discipline_of(name)
    rel_script = provenance.rel_to(root, script) if script else None
    if disc is None:
        disc = discipline or (
            cfg.discipline_for_path(rel_script) if rel_script else None
        )
        if disc is None:
            raise LedgerError(
                f"don't know which discipline '{name}' belongs to."
                f"put the script in a discipline folder or pass "
                f"discipline=... (one of: {', '.join(cfg.disciplines) or 'none configured'})"
            )
        if cfg.disciplines and disc not in cfg.disciplines:
            raise LedgerError(
                f"don't know this discipline: '{disc}'. known: {', '.join(cfg.disciplines)}."
            )
    # an existing name never moves files; asking for a different one is almost always a
    # name collision (two disciplines both wanting "S"), so refuse instead of overwriting
    elif discipline and discipline != disc:
        raise LedgerError(
            f"'{name}' already lives in params/{disc}.json, not {discipline}. "
            f"if that's a different quantity, give it a different name."
        )

    # everything read, or only the names given
    if inputs is not None:
        snap = {}
        for n in inputs:
            if n in read_log:
                snap[n] = read_log[n]
            elif n in reg:
                snap[n] = reg.get(n)["value"]
            else:
                raise _missing(n, reg)
    else:
        snap = dict(read_log)
    snap.pop(name, None)  # iterating on a value isn't a dependency on itself

    rec = {"value": value, "units": units.strip()}
    rec["status"] = status or ("computed" if snap else "assumed")
    # a verification survives a republish only if the number (and units) didn't change
    cleared = False
    if old and isinstance(old.get("verified"), dict):
        if verification_holds({**old, "value": rec["value"], "units": rec["units"]}):
            rec["verified"] = old["verified"]
        else:
            rec["verified"] = UNVERIFIED
            cleared = True
    else:
        rec["verified"] = UNVERIFIED
    # like desc, a reference outlives republishes unless a new one is given
    if reference or (old and old.get("reference")):
        rec["reference"] = reference or old["reference"]
    if desc or (old and old.get("desc")):
        rec["desc"] = desc or old["desc"]
    if note:
        rec["note"] = note
    if old and old.get("unfrozen"):
        rec["unfrozen"] = old["unfrozen"]  # pls keep reason visible in review
    if script and rel_script:
        rec["source"] = {"script": rel_script, "hash": provenance.file_hash(script)}
    if snap:
        rec["inputs"] = dict(sorted(snap.items()))
    rec["by"] = by or provenance.git_user(root)

    # if its unchanged the file is kept untouched so git shows no diff
    if old is not None:
        same = (
            values_equal(old.get("value"), rec["value"])
            and old.get("units") == rec["units"]
            and old.get("source") == rec.get("source")
            and old.get("note") == rec.get("note")
            and old.get("reference") == rec.get("reference")
            and old.get("status") == rec["status"]
            and set(old.get("inputs", {})) == set(rec.get("inputs", {}))
            and all(
                values_equal(old["inputs"][k], v)
                for k, v in rec.get("inputs", {}).items()
            )
        )
        if same:
            if not quiet:
                print(f"ledger: {name} unchanged ({_show(value)} {rec['units']})")
            return old

    rec["updated"] = (
        _dt.datetime.now(_dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    reg.set(disc, name, rec)
    reg.save(cfg.params_dir, disc)
    _cache.pop(cfg.root, None)

    if not quiet:
        ins = ", ".join(rec.get("inputs", {})) or "none"
        was = (
            f" (was {_show(old['value'])})"
            if old and not values_equal(old["value"], value)
            else ""
        )
        print(f"ledger: {name} = {_show(value)} {rec['units']}{was}  [inputs: {ins}]")
        if cleared:
            print(f"ledger: {name} was verified at a different value; verification cleared")
    return rec


def _show(v) -> str:
    if isinstance(v, float):
        return f"{v:.10g}"
    if isinstance(v, list):
        return f"[{len(v)} values]"
    return str(v)
