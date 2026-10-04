"""setup / sync / push / tag: git with the sharp edges removed.

Rules this module keeps:
  * nobody commits to or pushes main (hooks enforce it; push always uses a branch)
  * a merge only ever runs on a clean working tree, so aborting it is lossless
  * if pulling main into your branch conflicts, your work is still pushed
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import webbrowser
from pathlib import Path

from .config import Config, LedgerError

HOOKS_DIR = Path(__file__).resolve().parent / "hooks"


# ------------------------------------------------------------------ plumbing
def git(root: Path, *args, check=True, env=None) -> subprocess.CompletedProcess:
    e = dict(os.environ)
    if env:
        e.update(env)
    try:
        p = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, env=e)
    except FileNotFoundError:
        raise LedgerError("git isn't installed (or isn't on PATH). Install it from https://git-scm.com") from None
    if check and p.returncode != 0:
        raise LedgerError(f"git {' '.join(args)} failed:\n{(p.stderr or p.stdout).strip()}")
    return p


def out(root: Path, *args) -> str:
    return git(root, *args).stdout.strip()


def ok(root: Path, *args) -> bool:
    return git(root, *args, check=False).returncode == 0


def say(msg: str = ""):
    print(msg, flush=True)


def current_branch(root: Path) -> str | None:
    p = git(root, "symbolic-ref", "--short", "-q", "HEAD", check=False)
    return p.stdout.strip() or None


def is_dirty(root: Path) -> bool:
    return bool(out(root, "status", "--porcelain"))


def changed_paths(root: Path) -> list[tuple[str, str]]:
    """(status, path) for everything git would commit with `add -A`."""
    res = []
    for line in git(root, "status", "--porcelain", "-uall", "-z").stdout.split("\0"):
        if not line:
            continue
        code, path = line[:2], line[3:]
        res.append((code.strip() or "?", path))
    return res


def remote_main(cfg: Config) -> str:
    return f"origin/{cfg.main}"


def has_remote(root: Path) -> bool:
    return ok(root, "remote", "get-url", "origin")


def fetch(cfg: Config):
    if not has_remote(cfg.root):
        raise LedgerError("This repo has no 'origin' remote. Clone it from GitHub rather than copying the folder.")
    p = git(cfg.root, "fetch", "--prune", "origin", check=False)
    if p.returncode != 0:
        raise LedgerError("Couldn't reach GitHub:\n" + p.stderr.strip() +
                          "\nCheck your internet connection and that you're signed in (gh auth login).")


def ahead_count(root: Path, a: str, b: str) -> int:
    """Commits in a that aren't in b."""
    p = git(root, "rev-list", "--count", f"{b}..{a}", check=False)
    return int(p.stdout.strip() or 0) if p.returncode == 0 else 0


def branch_is_merged(cfg: Config, branch: str) -> bool:
    root = cfg.root
    if ok(root, "merge-base", "--is-ancestor", branch, remote_main(cfg)):
        return True
    # pushed before, and GitHub deleted the branch after merging the PR
    up = git(root, "rev-parse", "--abbrev-ref", f"{branch}@{{upstream}}", check=False)
    if up.returncode != 0:
        cfg_remote = git(root, "config", f"branch.{branch}.merge", check=False).stdout.strip()
        return bool(cfg_remote)       # had an upstream, now gone
    return False


def slug(s: str, n: int = 32) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return (s[:n].rstrip("-")) or "work"


def new_branch_name(root: Path, message: str) -> str:
    user = slug(out(root, "config", "user.name") or "me", 20)
    base = f"{user}/{_dt.date.today():%Y%m%d}-{slug(message)}"
    name, i = base, 2
    while ok(root, "rev-parse", "--verify", "-q", f"refs/heads/{name}") or \
            ok(root, "rev-parse", "--verify", "-q", f"refs/remotes/origin/{name}"):
        name, i = f"{base}-{i}", i + 1
    return name


def github_slug(root: Path) -> str | None:
    url = git(root, "remote", "get-url", "origin", check=False).stdout.strip()
    m = re.search(r"github\.com[:/](.+?)(?:\.git)?/?$", url)
    return m.group(1) if m else None


def have_gh() -> bool:
    if os.environ.get("LEDGER_NO_GH") or not shutil.which("gh"):
        return False
    return subprocess.run(["gh", "auth", "status"], capture_output=True).returncode == 0


def who(cfg: Config) -> str:
    return cfg.data.get("maintainer") or "the repo maintainer"


def merge_into_branch(cfg: Config, ref: str) -> list[str]:
    """Merge ref into the current (clean) branch. Returns conflicted files
    ([] on success). On conflict the merge is aborted, leaving the branch as it was."""
    root = cfg.root
    if is_dirty(root):
        raise LedgerError("internal: refusing to merge with uncommitted changes")
    if ok(root, "merge-base", "--is-ancestor", ref, "HEAD"):
        return []
    p = git(root, "merge", "--no-edit", ref, check=False)
    if p.returncode == 0:
        return []
    conflicted = out(root, "diff", "--name-only", "--diff-filter=U").splitlines()
    git(root, "merge", "--abort", check=False)
    return conflicted or ["(unknown files)"]


def catch_up(cfg: Config, branch: str) -> list[str]:
    """Bring in anything pushed to this branch by someone else (e.g. the maintainer
    fixing a conflict), then the latest main."""
    remote_branch = f"origin/{branch}"
    if ok(cfg.root, "rev-parse", "--verify", "-q", f"refs/remotes/{remote_branch}"):
        c = merge_into_branch(cfg, remote_branch)
        if c:
            return c
    return merge_into_branch(cfg, remote_main(cfg))


# ------------------------------------------------------------------ setup
def local_state_path(root: Path) -> Path:
    return root / ".ledger" / "local.json"


def setup(cfg: Config, interactive: bool = True) -> bool:
    root = cfg.root
    good = True

    def tick(msg):
        say(f"  ✓ {msg}")

    def cross(msg):
        nonlocal good
        good = False
        say(f"  ✗ {msg}")

    say(f"Setting up ledger in {root}")
    v = git(root, "--version").stdout.strip()
    tick(v)
    if not ok(root, "rev-parse", "--git-dir"):
        raise LedgerError(f"{root} is not a git repository. Clone the design repo from GitHub first.")

    for key, label in (("user.name", "your name"), ("user.email", "your email (the one on your GitHub account)")):
        val = git(root, "config", key, check=False).stdout.strip()
        if not val and interactive and sys.stdin.isatty():
            val = input(f"    git doesn't know {label}. Enter it: ").strip()
            if val:
                git(root, "config", "--global", key, val)
        if val:
            tick(f"git {key} = {val}")
        else:
            cross(f"git {key} not set: run  git config --global {key} \"...\"")

    # hooks (block commits/pushes to main and force pushes)
    hooks = HOOKS_DIR
    if os.name != "nt":
        for h in hooks.iterdir():
            if h.is_file():
                h.chmod(h.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    git(root, "config", "core.hooksPath", hooks.as_posix())
    tick("safety hooks installed (no commits/pushes to main, no force pushes)")

    # per-parameter merge driver
    py = Path(sys.executable).as_posix()
    git(root, "config", "merge.ledger.name", "ledger parameter merge")
    git(root, "config", "merge.ledger.driver", f'"{py}" -m ledger merge-driver %O %A %B')
    tick("parameter-aware merge driver configured")

    # remember which Python has ledger installed (MATLAB uses this)
    lp = local_state_path(root)
    lp.parent.mkdir(exist_ok=True)
    lp.write_text(json.dumps({"python": sys.executable, "path": os.environ.get("PATH", "")},
                          indent=2) + "\n", encoding="utf-8")
    gi = root / ".ledger" / ".gitignore"
    if not gi.exists():
        gi.write_text("*\n", encoding="utf-8")
    tick(f"Python for MATLAB: {sys.executable}")

    if has_remote(root):
        tick(f"origin = {out(root, 'remote', 'get-url', 'origin')}")
    else:
        cross("no 'origin' remote: clone the repo from GitHub instead of copying it")

    if shutil.which("gh"):
        if have_gh():
            tick("GitHub CLI signed in (ledger push will open pull requests for you)")
        else:
            cross("GitHub CLI installed but not signed in: run  gh auth login")
    else:
        say("  · GitHub CLI (gh) not installed: optional, but it lets `ledger push` open the PR for you.")
        say("    Without it, push prints a link to click instead. Install: https://cli.github.com")

    say("\nAll set." if good else "\nFix the ✗ items above, then run `ledger setup` again.")
    return good


def ensure_setup(cfg: Config):
    hp = git(cfg.root, "config", "core.hooksPath", check=False).stdout.strip()
    if hp != HOOKS_DIR.as_posix():
        git(cfg.root, "config", "core.hooksPath", HOOKS_DIR.as_posix())


# ------------------------------------------------------------------ sync
def sync(cfg: Config) -> int:
    root = cfg.root
    ensure_setup(cfg)
    say("Fetching from GitHub...")
    fetch(cfg)
    if (root / ".gitmodules").is_file():
        git(root, "submodule", "update", "--init", "--recursive", check=False)
    main, rmain = cfg.main, remote_main(cfg)
    br = current_branch(root)

    if br and br != main and branch_is_merged(cfg, br):
        p = git(root, "switch", main, check=False)
        if p.returncode != 0:
            say(f"Your branch '{br}' has been merged, but switching back to {main} would overwrite")
            say("uncommitted changes. Run  ledger push \"...\"  to save them first.")
            return 1
        say(f"'{br}' was merged; you're back on {main}.")
        merged_branch, br = br, main
    else:
        merged_branch = None

    if br == main or br is None:
        if br is None:
            say(f"You're not on a branch (detached HEAD). Ask {who(cfg)}, or run: git switch {main}")
            return 1
        if ahead_count(root, main, rmain):
            say(f"Your local {main} has commits that aren't on GitHub. `ledger push` will move them onto a branch.")
            return 1
        p = git(root, "merge", "--ff-only", rmain, check=False)
        if p.returncode != 0:
            say("Couldn't update: your uncommitted changes touch files that changed on GitHub.")
            say("Run  ledger push \"...\"  to save your work first, then sync again.")
            return 1
        if merged_branch:
            git(root, "branch", "-d", merged_branch, check=False)   # -d: only if fully merged
        say(f"Up to date with {rmain}.")
        return 0

    # unmerged work branch
    if is_dirty(root):
        say(f"You're on '{br}' with unsaved changes. Run  ledger push \"...\"  first;")
        say(f"it saves your work and brings in the latest {main} in one go.")
        return 1
    conflicted = catch_up(cfg, br)
    if conflicted:
        say(f"The latest {main} conflicts with your branch in: {', '.join(conflicted)}")
        say(f"Nothing was changed. Ask {who(cfg)} to resolve it.")
        return 2
    say(f"On '{br}' (PR still open), now including the latest {main}.")
    return 0


# ------------------------------------------------------------------ push
def push(cfg: Config, message: str, yes: bool = False, dry_run: bool = False,
         draft: bool = False) -> int:
    root = cfg.root
    ensure_setup(cfg)
    if not message.strip():
        raise LedgerError('Say what you did: ledger push "updated CG estimate"')
    if os.path.exists(os.path.join(root, ".git", "MERGE_HEAD")):
        raise LedgerError(f"A merge is in progress in this repo. Ask {who(cfg)} before pushing.")

    files = changed_paths(root)
    limit = float(cfg["max_file_mb"]) * 1024 * 1024
    big = [(p, (root / p).stat().st_size) for _, p in files if (root / p).is_file() and (root / p).stat().st_size > limit]
    if big:
        say("These files are too big for git:")
        for p, s in big:
            say(f"  {p}  ({s / 1e6:.1f} MB)")
        say("Add them (or their folder) to .gitignore and store them on OneDrive/Teams instead.")
        return 1

    if files:
        say("Files to save:")
        for code, p in files:
            say(f"  {code:>2}  {p}")
    else:
        say("No file changes.")
    if dry_run:
        return 0
    if files and not yes:
        if not sys.stdin.isatty():
            raise LedgerError("Not confirmed (run with --yes to skip the question).")
        if input("Push these? [Y/n] ").strip().lower() not in ("", "y", "yes"):
            say("Cancelled. Nothing changed.")
            return 1

    say("Fetching from GitHub...")
    fetch(cfg)
    main, rmain = cfg.main, remote_main(cfg)
    br = current_branch(root)
    if br is None:
        raise LedgerError(f"You're not on a branch (detached HEAD). Ask {who(cfg)}.")

    if br == main or branch_is_merged(cfg, br):
        new = new_branch_name(root, message)
        git(root, "switch", "-c", new)
        if br == main and ahead_count(root, main, rmain):
            # commits made on main by mistake now live on the new branch; reset main
            git(root, "branch", "-f", main, rmain)
        say(f"Working on new branch '{new}'.")
        br = new

    if files:
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", message)

    if ahead_count(root, br, rmain) == 0:
        say(f"Nothing to push: everything here is already in {main}.")
        return 0

    conflicted = catch_up(cfg, br)
    if conflicted and ok(root, "rev-parse", "--verify", "-q", f"refs/remotes/origin/{br}") \
            and not ok(root, "merge-base", "--is-ancestor", f"origin/{br}", "HEAD"):
        # can't fast-forward the remote branch; park the work on a fresh branch instead
        new = new_branch_name(root, message + " rescue")
        git(root, "switch", "-c", new)
        br = new

    say("Uploading...")
    p = git(root, "push", "-u", "origin", br, check=False)
    if p.returncode != 0:
        raise LedgerError("Push failed:\n" + (p.stderr or p.stdout).strip())

    url = open_pr(cfg, br, message, draft)

    if conflicted:
        say("")
        say(f"⚠ Your work is safely on GitHub (branch '{br}'), but it conflicts with")
        say(f"  recent changes on {main} in: {', '.join(conflicted)}")
        say(f"  Ask {who(cfg)} to resolve it. Don't try to fix it by hand.")
    else:
        say(f"\nDone. Branch '{br}' is up to date with {main} and on GitHub.")
    if url:
        say(f"Pull request: {url}")
    return 0


def open_pr(cfg: Config, branch: str, title: str, draft: bool) -> str | None:
    root = cfg.root
    if have_gh():
        p = subprocess.run(["gh", "pr", "list", "--head", branch, "--state", "open", "--json", "url",
                            "--jq", ".[0].url"], cwd=root, capture_output=True, text=True)
        if p.returncode == 0 and p.stdout.strip():
            return p.stdout.strip()
        args = ["gh", "pr", "create", "--base", cfg.main, "--head", branch, "--title", title,
                "--body", "Opened by `ledger push`. CI will comment with the ledger check."]
        if draft:
            args.append("--draft")
        p = subprocess.run(args, cwd=root, capture_output=True, text=True)
        if p.returncode == 0:
            return p.stdout.strip().splitlines()[-1]
        say("(Couldn't open the PR automatically: " + p.stderr.strip() + ")")
    gh = github_slug(root)
    if not gh:
        return None
    url = f"https://github.com/{gh}/compare/{cfg.main}...{branch}?expand=1"
    say("Open this link and press 'Create pull request' (if a PR already exists, GitHub will show it):")
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001
        pass
    return url


# ------------------------------------------------------------------ tags
def tag(cfg: Config, name: str, message: str | None) -> int:
    root = cfg.root
    fetch(cfg)
    if ok(root, "rev-parse", "--verify", "-q", f"refs/tags/{name}"):
        raise LedgerError(f"Tag '{name}' already exists.")
    git(root, "tag", "-a", name, remote_main(cfg), "-m", message or f"Baseline {name}")
    git(root, "push", "origin", f"refs/tags/{name}")
    say(f"Tagged {remote_main(cfg)} as '{name}' and pushed it. View any time with: git checkout {name}")
    return 0
