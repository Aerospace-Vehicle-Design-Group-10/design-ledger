"""The git workflow, with a local bare repo standing in for GitHub."""
import json
import os

import pytest
from conftest import Repo, git, make_repo

ALLOW = {"LEDGER_ALLOW_MAIN": "1"}


@pytest.fixture
def team(tmp_path):
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "--bare", "-b", "main", str(origin))

    # maintainer creates the repo (before hooks exist)
    m = make_repo(tmp_path / "maintainer")
    (m / ".gitattributes").write_text("params/*.json merge=ledger\n")
    (m / ".gitignore").write_text(".ledger/\n")
    git(m, "init", "-b", "main")
    _ident(m, "Lukas")
    git(m, "remote", "add", "origin", str(origin))
    maint = Repo(m)
    maint.set("MTOW", 712000, "N")
    maint.set("MLW", 600000, "N")
    git(m, "add", "-A")
    git(m, "commit", "-m", "init")
    git(m, "push", "-u", "origin", "main")
    maint.cli("setup", "--non-interactive", check=False)

    people = {}
    for name in ("alice", "bob"):
        d = tmp_path / name
        git(tmp_path, "clone", str(origin), str(d))
        _ident(d, name.title())
        r = Repo(d)
        r.cli("setup", "--non-interactive", check=False)
        people[name] = r
    return maint, people["alice"], people["bob"], origin


def _ident(d, name):
    git(d, "config", "user.name", name)
    git(d, "config", "user.email", f"{name.lower()}@example.com")


def branch(r: Repo) -> str:
    return git(r.root, "symbolic-ref", "--short", "HEAD").stdout.strip()


def remote_branches(r: Repo) -> list[str]:
    git(r.root, "fetch", "--prune")
    out = git(r.root, "branch", "-r").stdout.split()
    return [b.replace("origin/", "") for b in out if b.startswith("origin/") and "HEAD" not in b]


def github_merge(maint: Repo, br: str):
    """What pressing 'Merge pull request' on GitHub does (merge commit, delete branch)."""
    git(maint.root, "fetch", "origin")
    git(maint.root, "switch", "main")
    git(maint.root, "merge", "--ff-only", "origin/main")
    git(maint.root, "merge", "--no-ff", "-m", f"Merge {br}", f"origin/{br}", env={**os.environ, **ALLOW})
    git(maint.root, "push", "origin", "main", env={**os.environ, **ALLOW})
    git(maint.root, "push", "origin", "--delete", br, env={**os.environ, **ALLOW})


def publish(r: Repo, rel: str, name: str, expr: str, units="N"):
    r.script(rel, f'ledger.publish("{name}", {expr}, units="{units}")\n')
    r.run(rel)


# ------------------------------------------------------------------ guards
def test_commit_on_main_is_blocked(team):
    _, alice, _, _ = team
    (alice.root / "weights").mkdir(exist_ok=True)
    (alice.root / "weights/x.py").write_text("x = 1\n")
    git(alice.root, "add", "-A")
    p = git(alice.root, "commit", "-m", "oops", check=False)
    assert p.returncode != 0 and "blocked" in p.stderr


def test_push_to_main_is_blocked(team):
    _, alice, _, _ = team
    (alice.root / "weights").mkdir(exist_ok=True)
    (alice.root / "weights/x.py").write_text("x = 1\n")
    git(alice.root, "add", "-A")
    git(alice.root, "commit", "-m", "bypassed", env={**os.environ, **ALLOW})
    p = git(alice.root, "push", "origin", "main", check=False)
    assert p.returncode != 0 and "blocked" in p.stderr


def test_force_push_is_blocked(team):
    _, alice, _, _ = team
    publish(alice, "weights/a.py", "CG_x", 'ledger.get("MTOW") / 25000', "m")
    alice.cli("push", "cg", "--yes")
    git(alice.root, "commit", "--amend", "-m", "rewritten")
    p = git(alice.root, "push", "-f", "origin", branch(alice), check=False)
    assert p.returncode != 0 and "force push" in p.stderr


# ------------------------------------------------------------------ the normal loop
def test_push_then_merge_then_sync(team):
    maint, alice, bob, _ = team
    publish(alice, "weights/a.py", "CG_x", 'ledger.get("MTOW") / 25000', "m")
    out = alice.cli("push", "CG estimate", "--yes").stdout
    br = branch(alice)
    assert br.startswith("alice/") and "cg-estimate" in br
    assert br in remote_branches(alice)
    assert "Done." in out
    # main on GitHub is untouched until the PR is merged
    assert "CG_x" not in git(alice.root, "show", "origin/main:params/requirements.json").stdout

    github_merge(maint, br)

    out = alice.cli("sync").stdout
    assert "was merged" in out and branch(alice) == "main"
    assert br not in git(alice.root, "branch").stdout

    bob.cli("sync")
    assert "CG_x" in json.loads((bob.root / "params/weights.json").read_text())


def test_second_push_updates_same_branch(team):
    _, alice, _, _ = team
    publish(alice, "weights/a.py", "CG_x", "28.4", "m")
    alice.cli("push", "first", "--yes")
    br = branch(alice)
    publish(alice, "weights/a.py", "CG_x", "28.6", "m")
    alice.cli("push", "second", "--yes")
    assert branch(alice) == br


def test_new_work_after_merge_gets_new_branch(team):
    maint, alice, _, _ = team
    publish(alice, "weights/a.py", "CG_x", "28.4", "m")
    alice.cli("push", "first", "--yes")
    br = branch(alice)
    github_merge(maint, br)
    publish(alice, "weights/a.py", "CG_x", "28.6", "m")      # forgot to sync
    alice.cli("push", "second", "--yes")
    assert branch(alice) != br and "second" in branch(alice)


def test_parallel_publishes_to_same_file_merge_cleanly(team):
    maint, alice, bob, _ = team
    publish(alice, "weights/a.py", "CG_x", "28.4", "m")
    publish(bob, "weights/b.py", "CG_y", "0.0", "m")         # adjacent key, same file
    alice.cli("push", "alice cg", "--yes")
    bob.cli("push", "bob cg", "--yes")
    github_merge(maint, branch(alice))

    out = bob.cli("push", "catch up", "--yes").stdout          # brings in main via the merge driver
    assert "conflicts" not in out
    github_merge(maint, branch(bob))
    alice.cli("sync")
    w = json.loads((alice.root / "params/weights.json").read_text())
    assert set(w) == {"CG_x", "CG_y"}


def test_real_conflict_keeps_work_safe(team):
    maint, alice, bob, _ = team
    publish(alice, "weights/a.py", "CG_x", "28.4", "m")
    publish(bob, "weights/a.py", "CG_x", "29.9", "m")
    alice.cli("push", "alice", "--yes")
    github_merge(maint, branch(alice))
    p = bob.cli("push", "bob", "--yes")
    assert "conflicts" in p.stdout and "Lukas" in p.stdout
    # bob's work is on GitHub and his tree is clean (no half-finished merge)
    assert branch(bob) in remote_branches(bob)
    assert not git(bob.root, "status", "--porcelain").stdout.strip()
    assert not (bob.root / ".git/MERGE_HEAD").exists()
    assert json.loads((bob.root / "params/weights.json").read_text())["CG_x"]["value"] == 29.9


def test_commits_made_on_main_move_to_a_branch(team):
    _, alice, _, _ = team
    publish(alice, "weights/a.py", "CG_x", "28.4", "m")
    git(alice.root, "add", "-A")
    git(alice.root, "commit", "-m", "on main by mistake", env={**os.environ, **ALLOW})
    alice.cli("push", "fix", "--yes")
    assert branch(alice) != "main"
    assert git(alice.root, "rev-parse", "main").stdout == git(alice.root, "rev-parse", "origin/main").stdout


def test_sync_refuses_to_clobber_uncommitted_work(team):
    maint, alice, bob, _ = team
    publish(alice, "weights/a.py", "CG_x", "28.4", "m")
    alice.cli("push", "alice", "--yes")
    github_merge(maint, branch(alice))
    # bob edits the same file locally without pushing
    publish(bob, "weights/a.py", "CG_x", "30.0", "m")
    p = bob.cli("sync", check=False)
    assert p.returncode != 0 and "ledger push" in p.stdout
    assert json.loads((bob.root / "params/weights.json").read_text())["CG_x"]["value"] == 30


def test_large_files_are_refused(team):
    _, alice, _, _ = team
    (alice.root / "ledger.json").write_text(
        (alice.root / "ledger.json").read_text().replace('"project"', '"max_file_mb": 0.001, "project"'))
    (alice.root / "weights").mkdir(exist_ok=True)
    (alice.root / "weights/big.bin").write_bytes(b"x" * 5000)
    p = alice.cli("push", "big", "--yes", check=False)
    assert p.returncode != 0 and "too big" in p.stdout
    assert branch(alice) == "main"


def test_ci_style_check_against_main_catches_frozen_change(team):
    maint, alice, _, _ = team
    maint.cli("freeze", "poster-v1")
    git(maint.root, "commit", "-am", "freeze", env={**os.environ, **ALLOW})
    git(maint.root, "push", "origin", "main", env={**os.environ, **ALLOW})
    alice.cli("sync")
    # edit the JSON by hand to dodge the publish guard
    p = alice.root / "params/requirements.json"
    p.write_text(p.read_text().replace("712000", "700000"))
    r = alice.cli("check", "--since", "origin/main", "--no-lint", check=False)
    assert r.returncode == 1 and "frozen at poster-v1 but changed" in r.stdout
