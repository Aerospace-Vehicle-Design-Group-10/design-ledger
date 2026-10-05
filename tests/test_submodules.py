"""The design repo pins the ledger tools as a submodule; the pin must never go backwards.

Regression for: sync updated the submodule *before* fast-forwarding main, so the folder
kept the old tools, and the next `ledger push` (git add -A) committed the old pin back.
"""
import os

import pytest
from conftest import Repo, git, make_repo

ALLOW = {**os.environ, "LEDGER_ALLOW_MAIN": "1"}


@pytest.fixture
def world(tmp_path, monkeypatch):
    # local file:// submodules are disabled by default since git 2.38
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "protocol.file.allow")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "always")
    gh = tmp_path / "gh"
    gh.mkdir()
    git(gh, "init", "-q", "--bare", "-b", "main", "lib")
    git(gh, "init", "-q", "--bare", "-b", "main", "design")

    # the tools repo, v1
    lib = tmp_path / "lib-work"
    git(tmp_path, "clone", "-q", str(gh / "lib"), str(lib))
    _ident(lib, "Lukas")
    (lib / "VERSION").write_text("1\n")
    git(lib, "add", "-A")
    git(lib, "commit", "-qm", "v1")
    git(lib, "push", "-q", "origin", "main")

    # the design repo, pinning v1 (relative URL, like ../design-ledger)
    m = make_repo(tmp_path / "maintainer")
    (m / ".gitattributes").write_text("params/*.json merge=ledger\n")
    (m / ".gitignore").write_text(".ledger/\n")
    git(m, "init", "-q", "-b", "main")
    _ident(m, "Lukas")
    git(m, "remote", "add", "origin", str(gh / "design"))
    git(m, "submodule", "add", "-q", "../lib", "external/lib")
    maint = Repo(m)
    maint.set("MTOW", 712000, "N")
    git(m, "add", "-A")
    git(m, "commit", "-qm", "init", env=ALLOW)
    git(m, "push", "-q", "-u", "origin", "main", env=ALLOW)
    maint.cli("setup", "--non-interactive", check=False)

    people = []
    for name in ("alice", "bob"):
        d = tmp_path / name
        git(tmp_path, "clone", "-q", str(gh / "design"), str(d))
        _ident(d, name.title())
        git(d, "submodule", "update", "--init", "-q")          # what bootstrap.py does
        r = Repo(d)
        r.cli("setup", "--non-interactive", check=False)
        people.append(r)
    return lib, maint, people[0], people[1]


def _ident(d, name):
    git(d, "config", "user.name", name)
    git(d, "config", "user.email", f"{name.lower()}@example.com")


def release_v2(lib) -> str:
    (lib / "VERSION").write_text("2\n")
    git(lib, "commit", "-qam", "v2")
    git(lib, "push", "-q", "origin", "main")
    return git(lib, "rev-parse", "HEAD").stdout.strip()


def pin(r: Repo, ref="HEAD") -> str:
    return git(r.root, "ls-tree", ref, "external/lib").stdout.split()[2]


def checkout(r: Repo) -> str:
    return git(r.root / "external/lib", "rev-parse", "HEAD").stdout.strip()


def branch(r: Repo) -> str:
    return git(r.root, "symbolic-ref", "--short", "HEAD").stdout.strip()


def github_merge(maint: Repo, br: str):
    git(maint.root, "fetch", "-q", "origin")
    git(maint.root, "switch", "-q", "main")
    git(maint.root, "merge", "-q", "--ff-only", "origin/main")
    git(maint.root, "merge", "-q", "--no-ff", "-m", f"Merge {br}", f"origin/{br}", env=ALLOW)
    git(maint.root, "push", "-q", "origin", "main", env=ALLOW)
    git(maint.root, "push", "-q", "origin", "--delete", br, env=ALLOW)


def bump_tools(alice: Repo, maint: Repo, v2: str):
    """Act 10: someone deliberately moves the pin forward and it gets merged."""
    sub = alice.root / "external/lib"
    git(sub, "fetch", "-q", "origin")
    git(sub, "checkout", "-q", v2)
    out = alice.cli("push", "Update tools to v2", "--yes").stdout
    assert "Note:" not in out                       # an upgrade on GitHub isn't "fixed"
    assert pin(alice) == v2
    github_merge(maint, branch(alice))


# ------------------------------------------------------------------ tests
def test_sync_then_push_keeps_the_new_pin(world):
    """The exact bug: after a tools bump, a teammate syncs and pushes unrelated work."""
    lib, maint, alice, bob = world
    v2 = release_v2(lib)
    bump_tools(alice, maint, v2)

    bob.cli("sync")
    assert checkout(bob) == v2                      # folder follows main's new pin

    bob.set("MLW", 600000, "N")
    bob.cli("push", "MLW", "--yes")
    assert pin(bob) == v2                           # PR doesn't revert the tools
    assert pin(bob, f"origin/{branch(bob)}") == v2


def test_push_resets_a_checkout_that_is_behind(world):
    """Even if the folder was left behind some other way, push won't commit it."""
    lib, maint, alice, bob = world
    v1 = checkout(bob)
    v2 = release_v2(lib)
    bump_tools(alice, maint, v2)

    git(bob.root, "fetch", "-q")
    git(bob.root, "merge", "-q", "--ff-only", "origin/main")    # raw git: folder stays at v1
    assert checkout(bob) == v1 and pin(bob) == v2

    bob.set("MLW", 600000, "N")
    out = bob.cli("push", "MLW", "--yes").stdout
    assert "behind the version this repo uses" in out
    assert pin(bob) == v2 and checkout(bob) == v2


def test_push_refuses_a_pin_that_is_not_on_github(world):
    """A tools commit that only exists locally (what happened with b7e599c)."""
    lib, maint, alice, bob = world
    recorded = pin(bob)
    sub = bob.root / "external/lib"
    _ident(sub, "Bob")
    (sub / "VERSION").write_text("local\n")
    git(sub, "commit", "-qam", "local only")

    out = bob.cli("push", "x", "--dry-run").stdout
    assert "isn't on GitHub" in out and "push will reset it" in out
    assert checkout(bob) != recorded                # dry run changed nothing

    bob.set("MLW", 600000, "N")
    out = bob.cli("push", "MLW", "--yes").stdout
    assert "isn't on GitHub" in out
    assert pin(bob) == recorded and checkout(bob) == recorded


def test_edited_files_inside_the_tools_folder_dont_block_push(world):
    _, _, _, bob = world
    (bob.root / "external/lib/VERSION").write_text("hacking on the library\n")
    bob.set("MLW", 600000, "N")
    out = bob.cli("push", "MLW", "--yes").stdout
    assert "Done." in out and "external/lib" not in out
    # the edit is still there, untouched
    assert (bob.root / "external/lib/VERSION").read_text() == "hacking on the library\n"
