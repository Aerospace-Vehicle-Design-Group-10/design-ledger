"""Find numbers typed into code that look like registry values.

Heuristic by design: it only looks at literals with enough significant figures
(712000, 24.1, 3.75 -- not 0.5 or 2) and well-known constants are skipped.
Add `ledger: ignore` in a comment on a line to silence it.
"""
from __future__ import annotations

import io
import json
import math
import re
import subprocess
import tokenize
from dataclasses import dataclass
from pathlib import Path

# Physical/unit constants nobody should have to fetch from the registry.
COMMON = [
    9.81, 9.80665, 9.807, 3.14159, 3.141592653589793, 2.71828, 0.3048, 1852, 1609.344,
    0.4536, 0.45359237, 4.448, 4.44822, 101325, 1.225, 288.15, 287, 287.05, 287.058, 1.4,
    340.29, 340.3, 6894.76, 0.0254, 0.01745, 57.2958, 57.29577951308232, 3600, 86400,
    1.8, 459.67, 273.15, 0.0065, 1.716e-05, 1.789e-05, 5.2559, 216.65, 11000,
]

NUM_RE = re.compile(r"(?<![\w.])(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?(?![\w.])")
IGNORE_MARK = "ledger: ignore"


@dataclass
class Finding:
    file: str
    line: int
    literal: str
    matches: list[tuple[str, float]]


def sig_figs(lit: str) -> int:
    s = lit.lower().replace("_", "").lstrip("+-")
    mant = s.split("e")[0]
    if "." in mant:
        digits = mant.replace(".", "").lstrip("0")
    else:
        digits = mant.lstrip("0").rstrip("0")
    return len(digits)


def _py_numbers(text: str):
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.NUMBER:
                lit = tok.string
                if lit.lower().startswith(("0x", "0o", "0b")) or lit.lower().endswith("j"):
                    continue
                yield tok.start[0], lit
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return


def _strip_matlab_line(line: str) -> str:
    """Drop comments and string contents from a line of MATLAB."""
    out, i, n = [], 0, len(line)
    prev = ""
    while i < n:
        c = line[i]
        if c == "%":
            break
        if c == '"' or (c == "'" and not (prev.isalnum() or prev in ")]}.'_")):
            j = line.find(c, i + 1)
            if j == -1:
                break
            i = j + 1
            prev = c
            continue
        out.append(c)
        if not c.isspace():
            prev = c
        i += 1
    return "".join(out)


def _m_numbers(text: str):
    in_block = False
    for ln, raw in enumerate(text.splitlines(), 1):
        s = raw.strip()
        if s == "%{":
            in_block = True
            continue
        if s == "%}":
            in_block = False
            continue
        if in_block:
            continue
        for m in NUM_RE.finditer(_strip_matlab_line(raw)):
            yield ln, m.group(0)


def _ipynb_numbers(text: str):
    try:
        nb = json.loads(text)
    except ValueError:
        return
    for ci, cell in enumerate(nb.get("cells", []), 1):
        if cell.get("cell_type") != "code":
            continue
        src = "".join(cell.get("source", []))
        for ln, lit in _py_numbers(src):
            yield ci * 10000 + ln, lit           # cell*10000 + line, decoded in report


def _lines(text: str):
    return text.splitlines()


def scan_file(path: Path, rel: str, targets: list[tuple[str, float, str | None]], cfg_lint: dict) -> list[Finding]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    ext = path.suffix.lower()
    if ext == ".py":
        nums = _py_numbers(text)
    elif ext == ".m":
        nums = _m_numbers(text)
    elif ext == ".ipynb":
        nums = _ipynb_numbers(text)
    else:
        return []
    lines = _lines(text)
    tol = float(cfg_lint.get("rel_tol", 0.005))
    min_sf = int(cfg_lint.get("min_sig_figs", 3))
    skip = [float(v) for v in COMMON + list(cfg_lint.get("ignore_values", []))]
    out = []
    for ln, lit in nums:
        if sig_figs(lit) < min_sf:
            continue
        try:
            x = float(lit.replace("_", ""))
        except ValueError:
            continue
        if x == 0 or any(math.isclose(x, s, rel_tol=1e-4) for s in skip):
            continue
        if ext != ".ipynb" and 0 < ln <= len(lines) and IGNORE_MARK in lines[ln - 1]:
            continue
        # a script may contain the values it publishes itself (e.g. a chosen design point)
        hits = [(n, v) for n, v, src in targets if src != rel and abs(x - v) <= tol * abs(v)]
        if hits:
            out.append(Finding(rel, ln, lit, hits[:3]))
    return out


def tracked_files(root: Path) -> list[str]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "-co", "--exclude-standard"],
            cwd=root, capture_output=True, text=True, check=True,
        ).stdout.splitlines()
        return out
    except (subprocess.CalledProcessError, OSError):
        return [p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()]


def run(root: Path, records: dict, cfg_lint: dict, only: list[str] | None = None) -> list[Finding]:
    targets = []
    for name, rec in records.items():
        v = rec.get("value")
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v != 0:
            targets.append((name, float(v), (rec.get("source") or {}).get("script")))
    exts = set(cfg_lint.get("extensions", [".py", ".m", ".ipynb"]))
    excl = [e.strip("/") for e in cfg_lint.get("exclude", [])]
    files = only if only is not None else tracked_files(root)
    findings = []
    for rel in files:
        rel = rel.replace("\\", "/")
        if Path(rel).suffix.lower() not in exts:
            continue
        parts = rel.split("/")
        if any(p.startswith(".") for p in parts[:-1]):
            continue
        if any(rel == e or rel.startswith(e + "/") for e in excl):
            continue
        p = root / rel
        if p.is_file():
            findings += scan_file(p, rel, targets, cfg_lint)
    return findings


def where(f: Finding) -> str:
    if f.file.endswith(".ipynb"):
        return f"{f.file} cell {f.line // 10000} line {f.line % 10000}"
    return f"{f.file}:{f.line}"
