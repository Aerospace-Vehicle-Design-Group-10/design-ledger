"""`ledger check`: is the registry valid, and is everything up to date?"""

from __future__ import annotations

import ast
import operator
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import lint, provenance
from .config import Config
from .registry import NAME_RE, STATUSES, Registry, values_equal


@dataclass
class Item:
    severity: str  # error | warning | info
    code: str  # schema, stale, upstream, script, bounds, constraint, frozen, lint, size, cycle ...
    subject: str  # parameter name or file
    message: str
    discipline: str | None = None


@dataclass
class Report:
    items: list[Item] = field(default_factory=list)
    stale: dict = field(default_factory=dict)  # name -> [reasons]
    upstream: dict = field(default_factory=dict)  # name -> via
    rerun: list[list[str]] = field(default_factory=list)  # ordered groups of scripts
    cycles: list[list[str]] = field(default_factory=list)
    counts: dict = field(default_factory=dict)

    def add(self, *a, **k):
        self.items.append(Item(*a, **k))

    @property
    def errors(self):
        return [i for i in self.items if i.severity == "error"]

    @property
    def warnings(self):
        return [i for i in self.items if i.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors


# ------------------------------------------------------------------ helpers
def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:.6g}"
    if isinstance(v, list):
        return f"[{len(v)} values]"
    return str(v)


def tarjan(nodes, edges) -> list[list]:
    """Strongly connected components, in reverse topological order."""
    index, low, stack, on, out = {}, {}, [], set(), []
    counter = [0]

    def visit(v):
        work = [(v, iter(edges.get(v, ())))]
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on.add(v)
        while work:
            node, it = work[-1]
            advanced = False
            for w in it:
                if w not in index:
                    index[w] = low[w] = counter[0]
                    counter[0] += 1
                    stack.append(w)
                    on.add(w)
                    work.append((w, iter(edges.get(w, ()))))
                    advanced = True
                    break
                elif w in on:
                    low[node] = min(low[node], index[w])
            if advanced:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[node])
            if low[node] == index[node]:
                comp = []
                while True:
                    w = stack.pop()
                    on.discard(w)
                    comp.append(w)
                    if w == node:
                        break
                out.append(sorted(comp))

    for n in sorted(nodes):
        if n not in index:
            visit(n)
    return out


_OPS = {
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
}
_BIN = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
}


class _Missing(Exception):
    pass


def eval_constraint(expr: str, values: dict):
    """Evaluate e.g. 'MLW <= MTOW' or 'wing_front_spar + 0.2 < wing_aft_spar'.
    Returns True/False, or None if a name isn't in the registry yet."""
    tree = ast.parse(expr, mode="eval")

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.Name):
            if n.id not in values:
                raise _Missing(n.id)
            return values[n.id]
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
            return -ev(n.operand)
        if isinstance(n, ast.BinOp) and type(n.op) in _BIN:
            return _BIN[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.Compare):
            left = ev(n.left)
            for op, right in zip(n.ops, n.comparators):
                r = ev(right)
                if type(op) not in _OPS or not _OPS[type(op)](left, r):
                    return False
                left = r
            return True
        if isinstance(n, ast.BoolOp):
            vals = [ev(v) for v in n.values]
            return all(vals) if isinstance(n.op, ast.And) else any(vals)
        raise ValueError(f"unsupported expression: {ast.dump(n)}")

    try:
        return bool(ev(tree))
    except _Missing:
        return None


def changed_files(root: Path, since: str) -> list[str]:
    try:
        out = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=AMR", f"{since}...HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
    except subprocess.CalledProcessError:
        out = []
    # plus uncommitted/untracked work when run locally
    try:
        extra = subprocess.run(
            ["git", "ls-files", "-mo", "--exclude-standard"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
    except subprocess.CalledProcessError:
        extra = []
    return sorted(set(out) | set(extra))


# ------------------------------------------------------------------ the check
def run(cfg: Config, since: str | None = None, do_lint: bool = True) -> Report:
    rep = Report()
    root = cfg.root
    reg = Registry.load(cfg.params_dir)
    for e in reg.load_errors:
        rep.add("error", "schema", e.split(":")[0], e)
    recs = reg.records
    disc_of = {n: reg.discipline_of(n) for n in recs}

    # ---- schema
    for name, discs in reg.duplicates().items():
        rep.add(
            "error",
            "schema",
            name,
            f"defined in more than one file: {', '.join(discs)}",
        )
    known_discs = set(cfg.disciplines)
    for disc in reg.files:
        if known_discs and disc not in known_discs:
            rep.add(
                "warning",
                "schema",
                f"params/{disc}.json",
                f"'{disc}' is not a discipline in ledger.json",
            )
    for name, rec in recs.items():
        d = disc_of[name]
        if not NAME_RE.match(name):
            rep.add(
                "error",
                "schema",
                name,
                "invalid name (letters, digits, _; start with a letter; max 63)",
                d,
            )
        if not isinstance(rec, dict):
            rep.add("error", "schema", name, "record is not an object", d)
            continue
        for f in ("value", "units", "status", "by", "updated"):
            if f not in rec or rec[f] in (None, ""):
                rep.add("error", "schema", name, f"missing '{f}'", d)
        if rec.get("status") not in STATUSES:
            rep.add(
                "error",
                "schema",
                name,
                f"status must be one of {', '.join(STATUSES)}",
                d,
            )
        if not isinstance(rec.get("inputs", {}), dict):
            rep.add("error", "schema", name, "'inputs' must be an object", d)

    values = {n: r.get("value") for n, r in recs.items() if isinstance(r, dict)}
    numeric = {
        n: v
        for n, v in values.items()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    }

    # ---- bounds and constraints
    for name, (lo, hi) in cfg["bounds"].items():
        if name not in numeric:
            continue
        v = numeric[name]
        if (lo is not None and v < lo) or (hi is not None and v > hi):
            rep.add(
                "error",
                "bounds",
                name,
                f"{_fmt(v)} is outside [{lo}, {hi}]",
                disc_of.get(name),
            )
    for expr in cfg["constraints"]:
        try:
            res = eval_constraint(expr, numeric)
        except Exception as e:  # noqa: BLE001 - report bad config, don't crash
            rep.add("error", "constraint", expr, f"can't evaluate: {e}")
            continue
        if res is False:
            used = sorted(
                {
                    n.id
                    for n in ast.walk(ast.parse(expr, mode="eval"))
                    if isinstance(n, ast.Name)
                }
            )
            rep.add(
                "error",
                "constraint",
                expr,
                "violated (" + ", ".join(f"{n}={_fmt(numeric[n])}" for n in used) + ")",
            )

    # ---- staleness
    dependents: dict[str, set] = {}
    for name, rec in recs.items():
        if not isinstance(rec, dict):
            continue
        reasons = []
        for inp, used in (rec.get("inputs") or {}).items():
            dependents.setdefault(inp, set()).add(name)
            if inp not in values:
                reasons.append(f"input {inp} no longer exists")
            elif not values_equal(used, values[inp]):
                reasons.append(f"read {inp}={_fmt(used)}, now {_fmt(values[inp])}")
        src = rec.get("source") or {}
        script = src.get("script")
        if script:
            p = root / script
            if not p.is_file():
                reasons.append(f"script {script} no longer exists")
            elif src.get("hash") and provenance.file_hash(p) != src["hash"]:
                reasons.append(f"{script} has changed since this was published")
        if reasons:
            rep.stale[name] = reasons

    # downstream of anything stale
    frontier = list(rep.stale)
    while frontier:
        n = frontier.pop()
        for dep in sorted(dependents.get(n, ())):
            if dep not in rep.stale and dep not in rep.upstream:
                rep.upstream[dep] = n
                frontier.append(dep)

    for name, reasons in rep.stale.items():
        rep.add("warning", "stale", name, "; ".join(reasons), disc_of.get(name))
    for name, via in rep.upstream.items():
        rep.add(
            "warning", "upstream", name, f"depends on stale {via}", disc_of.get(name)
        )

    # ---- cycles (fine if converged; flagged so people know to iterate)
    edges = {
        n: set((r.get("inputs") or {}).keys()) & set(recs)
        for n, r in recs.items()
        if isinstance(r, dict)
    }
    for comp in tarjan(recs.keys(), edges):
        if len(comp) > 1:
            rep.cycles.append(comp)
            rep.add(
                "info",
                "cycle",
                " ↔ ".join(comp),
                "these depend on each other; re-run them until none is stale (converged)",
            )

    # ---- re-run order, by script
    affected = set(rep.stale) | set(rep.upstream)
    producer = {
        n: (r.get("source") or {}).get("script")
        for n, r in recs.items()
        if isinstance(r, dict)
    }
    scripts = {producer[n] for n in affected if producer.get(n)}
    sedges: dict[str, set] = {s: set() for s in scripts}
    for n in affected:
        s = producer.get(n)
        if not s:
            continue
        for inp in recs[n].get("inputs") or {}:
            t = producer.get(inp)
            if t and t != s and t in scripts:
                sedges[s].add(t)  # s needs t first
    rep.rerun = tarjan(scripts, sedges)  # dependencies come first
    no_script = sorted(n for n in affected if not producer.get(n))
    for n in no_script:
        if n in rep.stale:
            rep.add(
                "info",
                "manual",
                n,
                "has no source script; update it by hand (ledger set) if needed",
                disc_of.get(n),
            )

    # ---- frozen values vs main
    if since:
        base = Registry.load_at_ref(root, cfg["params_dir"], since)
        for name, brec in base.records.items():
            if not isinstance(brec, dict) or not brec.get("frozen"):
                continue
            head = recs.get(name)
            if head is None:
                rep.add(
                    "error",
                    "frozen",
                    name,
                    f"frozen at {brec['frozen']} but has been deleted",
                    base.discipline_of(name),
                )
                continue
            changed = not values_equal(
                head.get("value"), brec.get("value")
            ) or head.get("frozen") != brec.get("frozen")
            if changed:
                unf = head.get("unfrozen")
                if unf and unf.get("reason"):
                    rep.add(
                        "warning",
                        "frozen",
                        name,
                        f"was frozen at {brec['frozen']}; unfrozen by {unf.get('by', '?')}: {unf['reason']}",
                        disc_of.get(name),
                    )
                else:
                    rep.add(
                        "error",
                        "frozen",
                        name,
                        f"frozen at {brec['frozen']} but changed (use `ledger unfreeze {name} --reason ...`)",
                        disc_of.get(name),
                    )

    # ---- big files
    files_scope = changed_files(root, since) if since else None
    if files_scope:
        limit = float(cfg["max_file_mb"]) * 1024 * 1024
        for rel in files_scope:
            p = root / rel
            if p.is_file() and p.stat().st_size > limit:
                rep.add(
                    "error",
                    "size",
                    rel,
                    f"{p.stat().st_size / 1e6:.1f} MB is over the {cfg['max_file_mb']} MB limit; keep it out of git",
                )

    # ---- hard-coded numbers
    if do_lint:
        sev = cfg["lint"].get("level", "error")
        for f in lint.run(root, recs, cfg["lint"], only=files_scope):
            names = ", ".join(f"{n} ({_fmt(v)})" for n, v in f.matches)
            rep.add(
                sev,
                "lint",
                lint.where(f),
                f"literal {f.literal} looks like {names}; use ledger.get, or add a 'ledger: ignore' comment",
            )

    rep.counts = {
        "params": len(recs),
        "stale": len(rep.stale),
        "upstream": len(rep.upstream),
        "errors": len(rep.errors),
        "warnings": len(rep.warnings),
    }
    return rep
