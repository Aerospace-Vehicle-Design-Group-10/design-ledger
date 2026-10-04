# design-ledger

shared registry of design parameters for small teams working in **Python and MATLAB**,
with automatic provenance, staleness checking, and a git workflow.

```python
import ledger
W0 = ledger.get("MTOW")                    # read, and remember that we did
ledger.publish("CG_x", x_cg, units="m")    # write, recording inputs + script

```
```matlab
ledger.begin();
W0 = ledger.get("MTOW");
ledger.publish("CG_x", x_cg, "m");
```

This repo holds the lib. The project will use them from its own **design repo**, which contains
`ledger.json`, the `params/` registry and the analysis scripts, and includes this repo as a git
submodule at `external/design-ledger`. Team-facing usage instructions live in the design repo's README.

---

## How it works

### The registry

`params/<discipline>.json` in the design repo, one file per discipline:

```json
{
  "CG_x": {
    "value": 28.4,
    "units": "m",
    "status": "computed",
    "source": { "script": "weights/cg_estimate.py", "hash": "3f9c…" },
    "inputs": { "MTOW": 712000, "fuel_weight": 310000, "wing_x_LE": 24.1 },
    "by": "Lukas Campbell",
    "updated": "2026-10-04T14:03:00Z"
  }
}
```

| field | meaning |
|---|---|
| `value` | number, string, bool, or (nested) list of numbers |
| `units` | required; SI by convention, `-` for dimensionless |
| `status` | `requirement` (from the brief), `assumed` (entered by hand), `computed` (published with inputs) |
| `source` | script that published it and git's blob hash of that script (CRLF-normalised) |
| `inputs` | every parameter read before publishing, **with the value it had at the time** |
| `by`, `updated` | `git config user.name` of the publisher; UTC time |
| `desc`, `note` | optional free text |
| `frozen` / `unfrozen` | baseline tag it's frozen at / reason it was unfrozen |

Files are written in a canonical format (fixed key order, shortest exact numbers, integral floats
as integers), so a file only changes when a value does, whether Python or MATLAB wrote it.

### Provenance: how inputs are found

`get` appends `name → value` to an in-memory read log. `publish` copies the log into `inputs`.
Nothing is declared by hand. The log over-approximates (everything read so far in the run), which
can only cause false "stale" warnings, never missed ones. Narrow it where it matters:

- Python: `with ledger.step(): ...` (inputs = reads inside the block), or `publish(..., inputs=[...])`
- MATLAB: `ledger.begin()` at the top of each script (MATLAB's session outlives scripts), or `inputs=[...]`

A parameter is never its own input, so iterating on `MTOW` doesn't make `MTOW` stale.

The source credited is the file that **called `publish`** (nearest frame outside the ledger
package and the language's own library). A "run everything" driver doesn't hide which script
actually computed a value, and editing that script marks its outputs stale.

### Staleness

`ledger check` marks a value:

- **stale** if any recorded input value differs from its current value (relative tolerance 1e-9),
  an input no longer exists, or the source script's hash changed;
- **stale via upstream** if anything it depends on (transitively) is stale.

It compares values, not timestamps, so republishing an identical number changes nothing. Loops
(MTOW ↔ wing area) are allowed: a converged loop isn't stale, and `check` lists loops so people
know to iterate. Re-run order is a topological sort of the affected scripts, with loops grouped.

### Other checks

| check | severity |
|---|---|
| broken JSON, invalid names, missing fields, duplicate names | error |
| `bounds` in `ledger.json` (`"wing_taper": [0, 1]`) | error |
| `constraints` in `ledger.json` (`"MLW <= MTOW"`; arithmetic and chained comparisons allowed; skipped until all names exist) | error |
| frozen value changed vs `--since` ref without `unfreeze` | error |
| files over `max_file_mb` changed vs `--since` ref | error |
| hard-coded numbers in `.py`/`.m`/`.ipynb` (≥ `min_sig_figs` significant figures, within `rel_tol` of a registry value; common constants skipped; a script's own published values don't count; `ledger: ignore` on the line silences) | `lint.level` (default error) |
| stale / upstream | warning |
| loops, hand-entered stale values | info |

With `--since REF` (CI uses `origin/main`), the hard-coded-number scan only covers files changed
since REF.

### Git workflow

`ledger setup` (per clone):
- sets `core.hooksPath` to this package's `hooks/`. `pre-commit` refuses commits on `main`;
  `pre-push` refuses pushes to `main` and non-fast-forward (force) pushes.
  `LEDGER_ALLOW_MAIN=1` bypasses both.
- registers a merge driver (`merge=ledger` in `.gitattributes`) that merges `params/*.json` **per
  parameter**: different parameters in one file never conflict; only the same parameter changed
  two ways does.
- records the Python executable and `PATH` in `.ledger/local.json` for MATLAB.

`ledger push "msg"`: lists files → commits on a branch (creating `<user>/<date>-<msg>` if on `main`
or on an already-merged branch) → merges anything pushed to that branch by others, then
`origin/main` (on a clean tree, aborted cleanly on conflict) → pushes → opens or links the PR
(`gh` if signed in). On conflict the work is still pushed, to a fresh branch if necessary.

`ledger sync`: fetch → if the current branch was merged, switch to `main` and delete it →
fast-forward `main` (never a real merge with uncommitted changes) → on an open branch, bring in
`main` if the tree is clean.

---

## Reference

### Python API

| call | |
|---|---|
| `get(name)` | value; logged as a read |
| `publish(name, value, units, *, note=, desc=, inputs=, discipline=)` | write to the local registry |
| `record(name)` | full record dict (not logged) |
| `begin()` | clear the read log |
| `step()` | context manager: inner reads are the inputs of inner publishes |
| `override(**values)` | context manager: what-if values; publishing raises |
| `reads()` | current read log |
| `LedgerError` | raised for user-facing errors |

### MATLAB (`matlab/+ledger`)

`get`, `publish(name, value, units, note=, desc=, inputs=, discipline=)`, `record`, `begin`,
`override(name, value, ...)` / `override()`, `reads`, `sync`, `push(msg, draft=)`, `check`, `show`.
`get` and `record` are pure MATLAB (fast, cached). `publish` and the git commands call
`python -m ledger` with the Python recorded by `ledger setup`.

### CLI

```
ledger setup                       one-time, per clone
ledger sync                        get the latest main
ledger push "msg" [--draft] [-y]   save work to a branch + PR
ledger check [--since REF] [--no-lint] [--md F] [--json F] [--mention]
ledger show NAME                   record, staleness, inputs (used → current), users
ledger list [DISCIPLINE] [--stale] [--markdown]
ledger set NAME VALUE --units U [--discipline D] [--note ...] [--requirement]
ledger graph [NAME]                mermaid dependency graph, stale nodes highlighted
ledger export csv|tex|md [--out F]
ledger freeze TAG [--discipline ...] [--names ...]
ledger unfreeze NAME --reason "..."
ledger tag TAG                     annotated tag on origin/main, pushed
```

`python -m ledger ...` works everywhere `ledger` isn't on PATH.

### `ledger.json`

```json
{
  "maintainer": "Lukas",
  "params_dir": "params",
  "main_branch": "main",
  "disciplines": { "weights": { "folders": ["weights"], "owners": ["github-user"] } },
  "bounds": { "wing_taper": [0, 1], "MTOW": [0, null] },
  "constraints": ["MLW <= MTOW"],
  "max_file_mb": 20,
  "lint": { "level": "error", "min_sig_figs": 3, "rel_tol": 0.005, "ignore_values": [] },
  "export": { "csv_template": "...", "csv_map": "...", "csv_out": "...", "tex_out": "..." }
}
```

`owners` are GitHub usernames, @mentioned by CI in the stale-values issue. A new parameter goes to the
discipline whose `folders` contain the publishing script.

### Exports

- `csv`: fills a template CSV's `Value` column from a map
  `{"<Property>": {"param": "wing_front_spar", "scale": 100, "missing": "NaN"}}`.
- `tex`: `\input{params.tex}` then `\ledger{MTOW}` and `\ledgerunit{MTOW}`.
  Undefined names render as **??name??** instead of failing the build.
- `md`: a markdown table of everything.

---

## Development

```bash
python -m venv .venv && .venv/bin/pip install -e . pytest
.venv/bin/pytest -q
```

The tests include the full multi-user git workflow against a local bare repo (hooks, merge driver,
conflicts, sync after merge). No dependencies beyond the standard library; Python ≥ 3.9.
