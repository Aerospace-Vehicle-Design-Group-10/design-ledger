"""The `ledger` command."""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

from . import __version__, api, check, export, gitops, merge
from .config import Config, LedgerError, find_root
from .registry import Registry


def _cfg() -> Config:
    return Config.load(find_root())


# ------------------------------------------------------------------ report formatting
SEV_ICON = {"error": "✗", "warning": "!", "info": "·"}


def report_text(rep: check.Report) -> str:
    lines = []
    c = rep.counts
    order = ["schema", "bounds", "constraint", "frozen", "size", "lint", "stale", "upstream", "manual", "cycle"]
    titles = {
        "schema": "Registry format", "bounds": "Out of bounds", "constraint": "Constraints",
        "frozen": "Frozen values", "size": "Large files", "lint": "Hard-coded numbers",
        "stale": "Stale (an input or the script changed)", "upstream": "Stale via something upstream",
        "manual": "Hand-entered values that may need updating", "cycle": "Loops (iterate until converged)",
    }
    for code in order:
        items = [i for i in rep.items if i.code == code]
        if not items:
            continue
        lines.append(f"\n{titles[code]}:")
        for i in items:
            who = f"  [{i.discipline}]" if i.discipline else ""
            lines.append(f"  {SEV_ICON[i.severity]} {i.subject}: {i.message}{who}")
    if rep.rerun:
        lines.append("\nRe-run in this order:")
        for k, grp in enumerate(rep.rerun, 1):
            lines.append(f"  {k}. " + (grp[0] if len(grp) == 1 else "iterate together: " + ", ".join(grp)))
    status = "OK" if rep.ok else "FAILED"
    lines.append(
        f"\n{status}: {c['params']} parameters, {c['stale']} stale, {c['upstream']} stale via upstream, "
        f"{c['errors']} errors, {c['warnings']} warnings."
    )
    return "\n".join(lines).lstrip("\n")


def report_markdown(rep: check.Report, cfg: Config, mention: bool = False) -> str:
    c = rep.counts
    head = "### ✅ ledger check passed" if rep.ok else "### ❌ ledger check failed"
    md = ["<!-- ledger-report -->", head, "",
          f"{c['params']} parameters · **{c['stale']}** stale · **{c['upstream']}** stale via upstream · "
          f"**{c['errors']}** errors · {c['warnings']} warnings", ""]
    errs = rep.errors
    if errs:
        md += ["#### Must fix before merging", "", "| | What | Problem |", "|---|---|---|"]
        md += [f"| ✗ | `{i.subject}` | {i.message} |" for i in errs]
        md.append("")
    warn_other = [i for i in rep.warnings if i.code not in ("stale", "upstream")]
    if warn_other:
        md += ["#### Warnings", ""]
        md += [f"- `{i.subject}`: {i.message}" for i in warn_other]
        md.append("")
    stale = [i for i in rep.items if i.code in ("stale", "upstream")]
    if stale:
        md += ["#### Out of date", ""]
        by_disc: dict = {}
        for i in stale:
            by_disc.setdefault(i.discipline or "unassigned", []).append(i)
        for d in sorted(by_disc):
            owners = cfg.owners(d)
            tag = (" " + " ".join("@" + o for o in owners)) if (mention and owners) else ""
            md.append(f"**{d}**{tag}")
            md += [f"- `{i.subject}`: {i.message}" for i in by_disc[d]]
            md.append("")
    if rep.rerun:
        md += ["#### Re-run order", ""]
        for k, grp in enumerate(rep.rerun, 1):
            md.append(f"{k}. " + (f"`{grp[0]}`" if len(grp) == 1 else "iterate together: " + ", ".join(f"`{g}`" for g in grp)))
        md.append("")
    if rep.cycles:
        md += ["<details><summary>Loops in the dependency graph</summary>", ""]
        md += ["- " + " ↔ ".join(f"`{n}`" for n in comp) for comp in rep.cycles]
        md += ["", "</details>", ""]
    return "\n".join(md)


def report_json(rep: check.Report) -> str:
    return json.dumps({
        "ok": rep.ok, "counts": rep.counts,
        "items": [i.__dict__ for i in rep.items],
        "stale": rep.stale, "upstream": rep.upstream, "rerun": rep.rerun, "cycles": rep.cycles,
    }, indent=2, ensure_ascii=False)


# ------------------------------------------------------------------ commands
def cmd_check(a):
    cfg = _cfg()
    rep = check.run(cfg, since=a.since, do_lint=not a.no_lint)
    if a.md:
        Path(a.md).write_text(report_markdown(rep, cfg, mention=a.mention), encoding="utf-8")
    if a.json:
        Path(a.json).write_text(report_json(rep), encoding="utf-8")
    print(report_text(rep))
    return 0 if rep.ok else 1


def cmd_show(a):
    cfg = _cfg()
    reg = Registry.load(cfg.params_dir)
    recs = reg.records
    if a.name not in recs:
        raise LedgerError(f"'{a.name}' isn't in the registry.")
    r = recs[a.name]
    rep = check.run(cfg, do_lint=False)
    print(f"{a.name} = {r.get('value')} {r.get('units', '')}   [{reg.discipline_of(a.name)}, {r.get('status')}]")
    for k in ("desc", "note", "frozen"):
        if r.get(k):
            print(f"  {k}: {r[k]}")
    src = r.get("source") or {}
    print(f"  published by {r.get('by')} at {r.get('updated')}" + (f" from {src['script']}" if src.get("script") else ""))
    if a.name in rep.stale:
        print("  STALE: " + "; ".join(rep.stale[a.name]))
    elif a.name in rep.upstream:
        print(f"  STALE via {rep.upstream[a.name]}")
    else:
        print("  up to date")
    ins = r.get("inputs") or {}
    if ins:
        print("  inputs (value used → current):")
        for n, v in ins.items():
            cur = recs.get(n, {}).get("value", "MISSING")
            mark = "" if n in recs and check.values_equal(v, cur) else "   ← changed"
            print(f"    {n}: {v} → {cur}{mark}")
    users = sorted(n for n, rr in recs.items() if a.name in (rr.get("inputs") or {}))
    if users:
        print("  used by: " + ", ".join(users))
    return 0


def cmd_list(a):
    cfg = _cfg()
    reg = Registry.load(cfg.params_dir)
    recs = reg.records
    names = sorted(recs)
    if a.discipline:
        names = [n for n in names if reg.discipline_of(n) == a.discipline]
    if a.stale:
        rep = check.run(cfg, do_lint=False)
        names = [n for n in names if n in rep.stale or n in rep.upstream]
    if a.markdown:
        print(export.markdown_table(recs, names))
        return 0
    w = max([len(n) for n in names] + [4])
    for n in names:
        r = recs[n]
        v = r.get("value")
        vs = f"{v:.6g}" if isinstance(v, float) else str(v)
        fz = "  ❄" if r.get("frozen") else ""
        print(f"{n:<{w}}  {vs:>14} {r.get('units', ''):<8} {reg.discipline_of(n):<14} {r.get('status', '')}{fz}")
    print(f"\n{len(names)} parameters")
    return 0


def _parse_value(s: str):
    try:
        return json.loads(s)
    except ValueError:
        return s


def cmd_set(a):
    root = find_root()
    api.publish_with(root, a.name, _parse_value(a.value), a.units, note=a.note, desc=a.desc,
                     inputs=[], discipline=a.discipline, script=None, read_log={},
                     status="requirement" if a.requirement else "assumed")
    return 0


def cmd_publish_payload(a):
    """Called by MATLAB's ledger.publish with a JSON payload file."""
    p = json.loads(Path(a.payload).read_text(encoding="utf-8"))
    script = Path(p["script"]) if p.get("script") else None
    root = find_root(script, p.get("cwd"))
    reads = p.get("reads") or {}
    if isinstance(reads, list):        # MATLAB encodes an empty struct as []
        reads = {}
    inputs = p.get("inputs")
    if isinstance(inputs, str):
        inputs = [inputs]
    api.publish_with(root, p["name"], p["value"], p["units"], note=p.get("note") or None,
                     desc=p.get("desc") or None, inputs=inputs, discipline=p.get("discipline") or None,
                     script=script, read_log=reads)
    return 0


def cmd_graph(a):
    cfg = _cfg()
    recs = Registry.load(cfg.params_dir).records
    rep = check.run(cfg, do_lint=False)
    keep = set(recs)
    if a.name:
        if a.name not in recs:
            raise LedgerError(f"'{a.name}' isn't in the registry.")
        up, down, todo = set(), set(), [a.name]
        while todo:
            n = todo.pop()
            for i in (recs.get(n, {}).get("inputs") or {}):
                if i not in up:
                    up.add(i)
                    todo.append(i)
        todo = [a.name]
        while todo:
            n = todo.pop()
            for m, r in recs.items():
                if n in (r.get("inputs") or {}) and m not in down:
                    down.add(m)
                    todo.append(m)
        keep = up | down | {a.name}
    print("```mermaid")
    print("flowchart LR")
    for n in sorted(keep):
        if n in recs:
            print(f"  {n}[\"{n}\"]")
    for n in sorted(keep):
        for i in sorted((recs.get(n, {}).get("inputs") or {})):
            if i in keep:
                print(f"  {i} --> {n}")
    print("  classDef stale fill:#fdd,stroke:#c33")
    st = sorted((set(rep.stale) | set(rep.upstream)) & keep)
    if st:
        print("  class " + ",".join(st) + " stale")
    print("```")
    return 0


def cmd_export(a):
    cfg = _cfg()
    if a.what == "csv":
        path, missing = export.csv_export(cfg, Path(a.out) if a.out else None)
        print(f"Wrote {path.relative_to(cfg.root) if path.is_relative_to(cfg.root) else path}")
        if missing:
            print(f"{len(missing)} rows have no value yet:")
            for m in missing:
                print(f"  - {m}")
    elif a.what == "tex":
        path = export.tex_export(cfg, Path(a.out) if a.out else None)
        print(f"Wrote {path}. In LaTeX: \\input{{params.tex}} then \\ledger{{MTOW}} \\ledgerunit{{MTOW}}")
    elif a.what == "md":
        recs = Registry.load(cfg.params_dir).records
        text = export.markdown_table(recs)
        if a.out:
            Path(a.out).write_text(text + "\n", encoding="utf-8")
        else:
            print(text)
    return 0


def cmd_freeze(a):
    cfg = _cfg()
    reg = Registry.load(cfg.params_dir)
    n = 0
    for disc, recs in reg.files.items():
        if a.discipline and disc not in a.discipline:
            continue
        changed = False
        for name, r in recs.items():
            if a.names and name not in a.names:
                continue
            if r.get("frozen"):
                continue
            r["frozen"] = a.tag
            r.pop("unfrozen", None)
            changed = True
            n += 1
        if changed:
            reg.save(cfg.params_dir, disc)
    print(f"Froze {n} parameters at '{a.tag}'.")
    print(f"Next: ledger push \"freeze {a.tag}\", get it merged, then: ledger tag {a.tag}")
    return 0


def cmd_unfreeze(a):
    cfg = _cfg()
    reg = Registry.load(cfg.params_dir)
    disc = reg.discipline_of(a.name)
    if disc is None:
        raise LedgerError(f"'{a.name}' isn't in the registry.")
    r = reg.files[disc][a.name]
    if not r.get("frozen"):
        print(f"'{a.name}' isn't frozen.")
        return 0
    from .provenance import git_user
    r["unfrozen"] = {"from": r.pop("frozen"), "reason": a.reason, "by": git_user(cfg.root),
                     "at": _dt.date.today().isoformat()}
    reg.save(cfg.params_dir, disc)
    print(f"Unfroze {a.name}. The PR will show your reason to reviewers.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ledger", description="Shared design parameters with provenance.")
    p.add_argument("--version", action="version", version=f"ledger {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="command")

    s = sub.add_parser("setup", help="one-time setup on this computer")
    s.add_argument("--non-interactive", action="store_true")
    s.set_defaults(fn=lambda a: 0 if gitops.setup(_cfg(), interactive=not a.non_interactive) else 1)

    s = sub.add_parser("sync", help="get the latest shared values and code")
    s.set_defaults(fn=lambda a: gitops.sync(_cfg()))

    s = sub.add_parser("push", help="save your work to GitHub and open a pull request")
    s.add_argument("message", help='what you did, e.g. "updated CG estimate"')
    s.add_argument("--yes", "-y", action="store_true", help="don't ask for confirmation")
    s.add_argument("--dry-run", action="store_true", help="only list what would be saved")
    s.add_argument("--draft", action="store_true", help="open the PR as a draft (work in progress)")
    s.set_defaults(fn=lambda a: gitops.push(_cfg(), a.message, yes=a.yes, dry_run=a.dry_run, draft=a.draft))

    s = sub.add_parser("check", help="validate the registry and find stale values")
    s.add_argument("--since", help="compare with this git ref (CI uses origin/main)")
    s.add_argument("--no-lint", action="store_true", help="skip the hard-coded number scan")
    s.add_argument("--md", help="also write a markdown report to this file")
    s.add_argument("--json", help="also write a JSON report to this file")
    s.add_argument("--mention", action="store_true", help="@mention discipline owners in the markdown")
    s.set_defaults(fn=cmd_check)

    s = sub.add_parser("show", help="one parameter: value, inputs, who uses it")
    s.add_argument("name")
    s.set_defaults(fn=cmd_show)

    s = sub.add_parser("list", help="list parameters")
    s.add_argument("discipline", nargs="?")
    s.add_argument("--stale", action="store_true")
    s.add_argument("--markdown", action="store_true")
    s.set_defaults(fn=cmd_list)

    s = sub.add_parser("set", help="enter a value by hand (an assumption or requirement)")
    s.add_argument("name")
    s.add_argument("value", help="number, string, true/false, or JSON list")
    s.add_argument("--units", required=True)
    s.add_argument("--discipline")
    s.add_argument("--note")
    s.add_argument("--desc")
    s.add_argument("--requirement", action="store_true", help="mark as a requirement from the brief")
    s.set_defaults(fn=cmd_set)

    s = sub.add_parser("graph", help="print a mermaid dependency graph")
    s.add_argument("name", nargs="?", help="only what this depends on and what depends on it")
    s.set_defaults(fn=cmd_graph)

    s = sub.add_parser("export", help="csv (course template), tex (LaTeX macros), md (table)")
    s.add_argument("what", choices=["csv", "tex", "md"])
    s.add_argument("--out")
    s.set_defaults(fn=cmd_export)

    s = sub.add_parser("freeze", help="mark parameters frozen at a baseline (e.g. poster-v1)")
    s.add_argument("tag")
    s.add_argument("--discipline", nargs="*")
    s.add_argument("--names", nargs="*")
    s.set_defaults(fn=cmd_freeze)

    s = sub.add_parser("unfreeze", help="allow a frozen parameter to change, with a reason")
    s.add_argument("name")
    s.add_argument("--reason", required=True)
    s.set_defaults(fn=cmd_unfreeze)

    s = sub.add_parser("tag", help="tag the current main on GitHub (after a freeze is merged)")
    s.add_argument("name")
    s.add_argument("-m", "--message")
    s.set_defaults(fn=lambda a: gitops.tag(_cfg(), a.name, a.message))

    s = sub.add_parser("merge-driver", help=argparse.SUPPRESS)
    s.add_argument("files", nargs="*")
    s.set_defaults(fn=lambda a: merge.main(a.files))

    s = sub.add_parser("_publish", help=argparse.SUPPRESS)
    s.add_argument("--payload", required=True)
    s.set_defaults(fn=cmd_publish_payload)
    return p


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except (ValueError, OSError):
            pass
    a = build_parser().parse_args(argv)
    try:
        return int(a.fn(a) or 0)
    except LedgerError as e:
        print(f"ledger: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
