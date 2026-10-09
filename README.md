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
| `verified` | `"-"`, or `{by, at, value, units, note}` once someone has checked the number by hand (`ledger verify`) |

Files are written in a canonical format (fixed key order, shortest exact numbers, integral floats
as integers), so a file only changes when a value does, whether Python or MATLAB wrote it.

### Provenance: how inputs are found

`get` appends `name → value` to an in-memory read log. `publish` copies the log into `inputs`.
Nothing is declared by hand. By default the log over-approximates (everything read so far in the
run), which causes false "stale" warnings but never missed ones. Narrow it where it matters:

- Python: `with ledger.step(): ...` (inputs = reads inside the block), or `publish(..., inputs=[...])`
- MATLAB: `ledger.begin()` at the top of each script (MATLAB's session outlives scripts), or `inputs=[...]`

Narrowing can also *under*-report. A value read before a `step` block and used inside it is not
recorded, and anything that never went through `get` is invisible. See
[Exact behaviour and edge cases](#exact-behaviour-and-edge-cases).

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
`main` if the tree is clean → update submodules to the commits the repo now records.

Submodules (the design repo pins these tools at `external/design-ledger`): `push` never commits a
submodule checkout that is **behind** the recorded commit, or that is a commit **not on the
submodule's GitHub remote**. It resets the checkout and says so. A checkout **ahead** of the record
that is on GitHub is a deliberate upgrade and is committed. Edited files *inside* a submodule are
ignored: they're neither committed nor counted as unsaved work.

---

## Exact behaviour and edge cases

Written so that a teammate *or an AI agent* writing analysis code in a design repo can predict
exactly what the tool will do. Everything here describes the current code. Where the behaviour is a
known limitation, it says so.

### Rules for writing analysis code

1. **Never type a number another script or person produced.** Get it with `ledger.get("NAME")`.
   Typed-in copies, values read from your own files, and values passed in from other programs are
   invisible to provenance.
2. **Read a value right before you use it.** Every `publish` records *everything read so far*, so
   reading all inputs at the top makes every output depend on all of them (false stale warnings).
3. **If you use `with ledger.step():`, call `get` inside the block for every value used inside it.**
   Values read before the block are *not* recorded for publishes inside it (missed stale warnings).
4. **Publish from a `.py` or `.m` file inside the repo, in the folder of its discipline**
   (`weights/`, `wing/`, …). New parameters go to that discipline's file.
5. **Units are required. Use SI, angles in `deg`, percentages as fractions.** The tool stores the
   units string and never converts or checks it.
6. **MATLAB: the first line of every publishing script is `ledger.begin();`.**
7. **Don't publish in a tight loop** (each publish rewrites a JSON file; in MATLAB each one also
   starts Python). Compute, then publish once.
8. **Never edit `params/*.json` by hand, except to delete a parameter or fix a broken file**, and
   run `ledger check` afterwards.
9. **Share work only with `ledger push "message"`**; get others' work only with `ledger sync`.

### Reading values and what counts as an input

| Situation | What happens |
|---|---|
| `x = get("A")` then `publish("P", ...)` | `P.inputs` contains `A` with the value it had **when it was read**. |
| Several publishes in one run | Each records the reads made **so far**: earlier publishes have fewer inputs, later ones more. |
| A value is used but was never `get`-ed (literal, `np.load`, constant in a helper module, a value from another script's output file) | Not an input. If it changes, nothing goes stale. Only literals are partly caught, by the hard-coded-number check. |
| `with ledger.step():` block | The block starts with an **empty** read log. Publishes inside record only reads made inside. On exit, the block's reads are added to the enclosing log, so publishes after the block see them. Blocks nest. |
| `W0 = get("MTOW")` **before** a `step`, `W0` used inside it | **MTOW is not recorded** for publishes inside the block. A silent under-report: re-`get` inside the block, or use `inputs=`. |
| `publish(..., inputs=["A", "B"])` | Exactly these names. Each value comes from the read log if it was read, otherwise from the **current** registry. A name not in the registry raises. |
| `publish(..., inputs=[])` | No inputs. The value's `status` becomes `assumed`, even though a script published it. |
| A script reads `P` and then publishes `P` (iteration) | `P` is never recorded as its own input. |
| `ledger.begin()` (Python and MATLAB) | Clears the read log at every level, including inside an open `step` block. Reads after it are recorded as normal. |
| Python: one process = one log | Running two scripts in separate `python` calls never mixes their reads. In **Jupyter/IPython** the log lasts the whole kernel: call `ledger.begin()` at the top of a cell that publishes. |
| MATLAB: one session = one log | Reads from a script run earlier in the session **are** recorded by the next script unless it calls `ledger.begin()`. |
| `ledger.record("A")` | Returns the full record. **Not** logged as a read. |
| `ledger.reads()` | Shows what a publish right now would record. |
| `get` of a value published earlier in the same run | Returns the new value; that read is logged with the new value. |
| `with ledger.override(A=1.0):` / MATLAB `ledger.override("A", 1.0)` | `get("A")` returns 1.0 and is **not** logged. **Any** publish raises while an override is active, even of unrelated names. MATLAB overrides last until `ledger.override()` clears them. |
| Misspelled name | `get` raises `LedgerError` with close matches. Names are case-sensitive (`MTOW` ≠ `mtow`). |

### Where a value is credited from (`source`)

| Situation | What happens |
|---|---|
| Python | `source.script` is the file that **called** `publish`: the nearest stack frame outside the ledger package and the base Python standard library. |
| `publish` inside a helper function in another file | The helper's file is credited, not the script you ran. |
| Driver script `run_all.py` calling other scripts' functions | Each value is credited to the file that called `publish`. |
| MATLAB | The nearest `.m`/`.mlx` file on the call stack outside `+ledger` and `matlabroot`, so a function file that calls `publish` is the source. |
| Jupyter / IPython / the Python REPL / MATLAB command window | No `source` recorded. Script-change staleness can't apply; the value can't be re-run automatically. |
| Script outside the repo (but cwd inside it) | Works, but no `source` is recorded. |
| `source.hash` | git's blob hash of **that one file** (CRLF → LF first, so Windows and macOS agree). Any edit, even a comment, marks its outputs stale. Edits to **helper modules it imports, or data files it loads, are not detected**. |

### Values and types

| Situation | What happens |
|---|---|
| Allowed types | int, float, bool, str, (nested) lists of these. numpy scalars/arrays and tuples are converted to plain numbers/lists. |
| `None`, `NaN`, `inf` (incl. MATLAB `NaN`) | Rejected with `LedgerError`. |
| A one-element list, e.g. `[5.0]` or a MATLAB 1×1 | Stored as the scalar `5`. |
| A float that is a whole number, e.g. `712000.0` | Stored as `712000`. **Python `get` returns an `int`.** |
| A list from `get` | Plain Python `list`; wrap in `np.asarray`. MATLAB returns numeric JSON arrays as **column vectors**. |
| A string from `get` in MATLAB | A `char` array. |
| Comparing values (staleness, "unchanged") | Numbers equal within relative tolerance 1e-9; lists compared element by element. |
| Republishing identical value, units, note, status, source and inputs | Prints `unchanged`; the file isn't touched (no git diff). |
| Republishing **without** `note=` | The previous note is **removed** (`desc` is kept). That counts as a change. |
| Publishing the same name twice in one run | The last one wins. |
| Lists/strings in `bounds`, `constraints`, lint, CSV/TeX exports | Skipped by bounds, constraints and lint; exported as-is to CSV; skipped by TeX. |

### Names, units, disciplines, ownership

| Situation | What happens |
|---|---|
| Name rules | `^[A-Za-z][A-Za-z0-9_]{0,62}$`, unique across **all** `params/*.json`. |
| A **new** name | Goes into `params/<discipline>.json`, where the discipline's `folders` (in `ledger.json`) contain the publishing script; the longest matching folder wins. If none match: `discipline=` is required, else `LedgerError`. |
| An **existing** name | Stays in its current file. Passing a *different* `discipline=` raises `LedgerError` ("already lives in params/X.json"), because that's almost always two disciplines wanting the same name: rename one. Without `discipline=`, publishing an existing name from any folder overwrites it. |
| Who may change a value | **Anyone.** `owners` in `ledger.json` only decides who CI @mentions; it doesn't restrict writes. Review happens in the PR. |
| Units | Required, non-empty, otherwise free text. `"m"` vs `"mm"` mismatches are **not** detected. |
| Renaming a parameter | No command. Publish the new name, update the scripts that `get` the old one, then delete the old entry from its JSON file. Anything that still records the old name as an input shows *"input X no longer exists"* until re-run. |
| Deleting a parameter | Remove its entry from the JSON by hand. Frozen ones fail CI unless unfrozen first. |
| `ledger set NAME VALUE` parsing | VALUE is parsed as JSON first, else kept as text: `1e-4` → number, `true` → bool, `[1, 2]` → list, `NACA_0012` → text, **`0012` → text "0012"** (JSON forbids leading zeros), `'"NACA 0012"'` → text. `status` is `assumed` (or `requirement` with `--requirement`); no inputs, no source. |

### Staleness

| Situation | What happens |
|---|---|
| An input's current value ≠ the recorded one | **Stale** (warning). |
| An input no longer exists | Stale. |
| The source script changed or was moved/renamed | Stale (*"has changed"* / *"no longer exists"*). Moving a script means re-running it from its new path. |
| Anything depending on a stale value | **Stale via upstream**, transitively. |
| An input changed and changed back | **Not** stale: values are compared, not timestamps. |
| A script edited and re-run, outputs identical | Its outputs are fresh, and so is everything downstream. |
| Dependency loop (A reads B, B reads A) | Allowed. Fresh once converged (each was computed with the other's current value). Listed as *info*; re-run order shows *"iterate together"*. |
| Stale value with no source (`ledger set`, notebooks) | Reported as *"has no source script; update it by hand"*. |
| Stale values in CI | **Warnings only.** They never fail a PR. On `main`, CI keeps one *"Stale values (ledger)"* issue, @mentioning `owners`, and closes it when everything is fresh. |

### What fails `ledger check` (exit code 1, red CI)

| Check | Notes |
|---|---|
| Broken JSON, invalid/duplicate names, missing `value`/`units`/`status`/`by`/`updated`, bad `status` | |
| `bounds` | `[min, max]`, `null` = open. Numbers only. |
| `constraints` | Python-like expressions over names and numbers: `+ - * / **`, comparisons (chainable), `and`/`or`, unary minus. **Skipped until every name in it exists.** |
| Frozen value changed or deleted | **Only with `--since REF`** (what CI runs on PRs). Locally, the publish guard blocks it instead; hand-edits are only caught in CI. |
| Changed file over `max_file_mb` | Only with `--since`. `ledger push` also refuses them up front. |
| Hard-coded numbers | When `lint.level` is `error` (the default). See below. |

### The hard-coded-number check (lint)

| Rule | Effect |
|---|---|
| Files scanned | `.py`, `.ipynb` (code cells) and `.m` tracked or untracked-but-not-ignored, excluding `external/`, `params/`, `export/`, `.venv/`, `venv/` and any hidden folder. **`.mlx` live scripts are not scanned.** With `--since` (CI), only files changed since REF. |
| Significant figures | Only literals with **≥ 3 significant figures** are compared (`min_sig_figs`). Trailing zeros of integers don't count: `712000` = 3 → checked; `3000` = 1, `150` = 2, `0.82` = 2 and `9.5` = 2 → **never flagged**, even if they copy a registry value. |
| Match | Within 0.5 % (`rel_tol`) of any non-zero numeric registry value, so rounded copies (`3.397e6` for 3397330) are caught. |
| Not flagged | Common physical/unit constants (g, ISA sea-level values, unit conversions, …), anything in `lint.ignore_values`, values the **same file** publishes (a chosen design point is fine), comments and MATLAB strings. |
| Silencing one line | A comment containing `ledger: ignore` on that line (not supported in notebooks). |
| A coincidence (a literal that happens to be near a registry value) | Flagged. Add `ledger: ignore` with a comment saying why. |

### Freezing

| Situation | What happens |
|---|---|
| `ledger freeze TAG` | Marks every not-yet-frozen parameter (or `--discipline` / `--names`) as frozen at TAG. Local change: push and merge it, then `ledger tag TAG`. |
| Publishing or `ledger set` on a frozen name | `LedgerError`. Re-running a script stops at the first frozen value it publishes; values it published earlier in that run are already written. |
| Parameters created **after** a freeze | Not frozen. Work on new values continues normally. |
| `ledger unfreeze NAME --reason "…"` | Removes `frozen` and records `unfrozen: {from, reason, by, at}`, which stays on the record (shown to reviewers by CI). One name per call; there's no bulk unfreeze. |
| Requirements from the brief | Frozen at `brief` from the start. |
| Tag vs freeze | Tag every submission (a bookmark that blocks nothing). Freeze only when the design must stop changing. |

### Verification (`verified`)

| Situation | What happens |
|---|---|
| New or republished value | `"verified": "-"`. Records written before this field existed have no `verified` key, which means the same. |
| `ledger verify NAME... --note "how"` | Sets `verified` to `{by, at, value, units, note}` (`by` = git user name). Refuses if any NAME is stale or stale via upstream, and then verifies none of them; `--force` overrides. Doesn't change the value, so it works on frozen values too. |
| Verifying an already-verified value | No-op, unless a new `--note` is given (which re-verifies under your name). |
| Republish/`ledger set` with the **same** value and units (e.g. a re-run after editing the script) | Verification kept. |
| Republish with a **different** value or units | Verification reset to `"-"`, with a printed notice. |
| Value hand-edited in the JSON | `verified` no longer matches. `ledger check` warns *"verified … but it's now …"*, the value counts as unverified, and `show` says `OUTDATED`. |
| Inputs change but the value isn't re-run | Still counts as verified (the number itself is unchanged), but `verify` refuses stale values, and the value shows up as stale anyway. |
| `ledger unverify NAME...` | Back to `"-"`. |
| Malformed `verified` (anything but `"-"` or the object) | Schema **error**. |
| In CI (`--since`) | Not an error either way. The PR comment lists *Verification changes* (who verified what, with their note, or "verification removed"), and the summary line shows `N/M verified`. |
| What it is not | A permission system. Anyone can run `ledger verify`; review the *Verification changes* in the PR. |

### Git workflow (`ledger push` / `ledger sync`)

| Situation | What happens |
|---|---|
| What `push` commits | **Everything** changed or new in the repo that isn't gitignored (`git add -A`), after showing the list and asking. Not just parameters. |
| Pushing again while your PR is open | Goes to the **same branch and PR**. To start unrelated work in a separate PR, get the first one merged first (or `git switch -c you/other origin/main` yourself; `push` pushes whatever branch you're on). |
| After your PR is merged | The next `push` or `sync` notices and starts a new branch / returns you to `main`. This relies on merge commits or GitHub auto-deleting merged branches. |
| PR title | The message of the push that created the branch; later push messages only become commit messages. |
| `sync` with uncommitted changes | On `main`: fast-forwards if your changes don't touch updated files, otherwise refuses and changes nothing. On an open branch: refuses (run `push` first). |
| Two people change **different** parameters in one file | Merged per parameter locally. On GitHub the PR may still say *"This branch has conflicts"*: run `ledger push "…"` again and it goes away. |
| Two people change the **same** parameter | `push` still uploads your work, leaves your folder clean, and asks you to get the maintainer to resolve. During resolution the file stays valid JSON holding one side. |
| Commit or push to `main`, force push | Blocked by local hooks. They're bypassed by `--no-verify`, `LEDGER_ALLOW_MAIN=1`, edits on github.com, or a clone where `ledger setup` never ran. |
| Files over `max_file_mb` | `push` refuses before committing anything. |
| Tools folder (`external/design-ledger`) | Kept at the commit the repo records. Stale/unpushed checkouts are reset rather than committed; edits inside it are ignored. |
| Running two publishing scripts **at the same time** | Unsafe: each rewrites its whole discipline file, so one update can be lost. Run publishers one after another. |

### Not supported (by design or yet)

- Partial pushes (`push` takes all changes; use plain git on a branch for that).
- Unit conversion or unit checking.
- Detecting changes to imported helper modules or data files (only the publishing file is fingerprinted).
- Bulk unfreeze, renaming, deleting parameters via a command.
- Restricting who may change which discipline.

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
`override(name, value, ...)` / `override()`, `reads`, `sync`, `push(msg, draft=)`, `check`, `show`,
`verify(names, note=)`.
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
ledger verify NAME... [--note "how"] [--force]   record a manual check of the current value
ledger unverify NAME...
ledger list --unverified           values nobody has checked yet
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
