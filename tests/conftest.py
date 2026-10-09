import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"

CONFIG = {
    "project": "test",
    "maintainer": "Lukas",
    "disciplines": {
        "requirements": {"folders": [], "owners": ["lukas"]},
        "weights": {"folders": ["weights"], "owners": ["alice"]},
        "wing": {"folders": ["wing"], "owners": ["bob"]},
        "tail": {"folders": ["tail"], "owners": []},
    },
    "bounds": {"wing_taper": [0, 1]},
    "constraints": ["MLW <= MTOW"],
}


def env_for(root: Path, **extra) -> dict:
    e = dict(os.environ)
    e["PYTHONPATH"] = str(SRC) + os.pathsep + e.get("PYTHONPATH", "")
    e["LEDGER_NO_GH"] = "1"
    e.pop("LEDGER_ROOT", None)
    e.update(extra)
    return e


def make_repo(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    (root / "ledger.json").write_text(json.dumps(CONFIG, indent=2))
    (root / "params").mkdir(exist_ok=True)
    for d in ("weights", "wing", "tail"):
        (root / d).mkdir(exist_ok=True)
    return root


class Repo:
    def __init__(self, root: Path):
        self.root = root

    def script(self, rel: str, body: str) -> Path:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("import ledger\n" + body)
        return p

    def run(self, rel: str, check=True):
        p = subprocess.run([sys.executable, rel], cwd=self.root, env=env_for(self.root),
                           capture_output=True, text=True)
        if check and p.returncode != 0:
            raise AssertionError(p.stdout + p.stderr)
        return p

    def cli(self, *args, check=True, cwd=None, input=None):
        p = subprocess.run([sys.executable, "-m", "ledger", *args], cwd=cwd or self.root,
                           env=env_for(self.root), capture_output=True, text=True, input=input)
        if check and p.returncode != 0:
            raise AssertionError(f"ledger {' '.join(args)} failed:\n{p.stdout}\n{p.stderr}")
        return p

    def params(self, disc: str) -> dict:
        return json.loads((self.root / "params" / f"{disc}.json").read_text())

    def set(self, name, value, units="-", disc="requirements", reference="test fixture"):
        args = ["set", name, json.dumps(value), "--units", units, "--discipline", disc]
        if reference:
            args += ["--reference", reference]
        self.cli(*args)


@pytest.fixture
def repo(tmp_path):
    return Repo(make_repo(tmp_path / "design"))


def git(cwd, *args, env=None, check=True):
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=env)
    if check and p.returncode != 0:
        raise AssertionError(f"git {' '.join(args)}:\n{p.stdout}\n{p.stderr}")
    return p
