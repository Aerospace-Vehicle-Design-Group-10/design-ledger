"""Finds the design repo and reads its ledger"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_NAME = "ledger.json"

DEFAULTS = {
    "project": "",
    "params_dir": "params",
    "main_branch": "main",
    "disciplines": {  # split is on the cw sheet
        # folders: [], (folder name/s in the design repo)
        # owners: [], (whos working on it/responsible)
    },
    "bounds": {
        # variable_name: [min, max] (eg MTOW [0, null])
    },
    "constraints": [
        # eg "MLW <= MTOW", "W_payload + W_fuel_design < MTOW"
    ],
    # statuses that must say where the number came from ("reference"). a script that
    # computed a value is its own source; requirements come from the brief
    "require_reference": ["assumed"],
    "max_file_mb": 20,  # files bigger than this are refused by push and flagged by CI
    "lint": {  # the hard-coded number check; ledger.json can override any of these
        "level": "error",  # "error" blocks CI, "warning" only reports
        "min_sig_figs": 3,  # literals with fewer sig figs are ignored (0.5, 2, ...)
        "rel_tol": 0.005,  # how close a literal must be to a registry value to flag
        "extensions": [".py", ".m", ".ipynb"],
        "exclude": ["external", "params", "export", ".venv", "venv"],
        "ignore_values": [],  # extra literal values never to flag
    },
    "export": {  # where `ledger export` reads/writes
        "csv_template": "export/designparams_template.csv",
        "csv_map": "export/designparams_map.json",
        "csv_out": "export/designparams.csv",
        "tex_out": "export/params.tex",
    },
}


class LedgerError(Exception):
    """an error w a msg meant for whoevers running the command"""


# merges `base` with `over`
def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)

    for k, v in over.items():
        # basically if its a dict we recurse
        if (
            isinstance(v, dict)
            and isinstance(out.get(k), dict)
            and k != "disciplines"
            and k != "bounds"
        ):
            out[k] = _merge(out[k], v)
        else:  # the full disciplines and bounds dicts will get replaced, while others will just have the field value overwritten
            out[k] = v
    return out


# finds the ledger.json file
def find_root(*starts) -> Path:
    # we walk up from each start (file or dir)

    # is it in the env
    env = os.environ.get("LEDGER_ROOT")

    # potential candidates
    candidates = [Path(env)] if env else []  # incase its not in env
    candidates += [Path(s) for s in starts if s]
    candidates.append(Path.cwd())

    for c in candidates:
        # the candidate path
        c = c.resolve()

        # we want directories not files
        if c.is_file():
            c = c.parent

        # check each candidate directory for the config file
        for d in [c, *c.parents]:
            if (d / CONFIG_NAME).is_file():
                return d
    raise LedgerError(
        f"couldn't find {CONFIG_NAME}. run from inside the design repo (or set LEDGER_ROOT to its path)"
    )


@dataclass
class Config:
    root: Path
    data: dict = field(default_factory=dict)

    # loads the config json data and creates the config cls
    @classmethod
    def load(cls, root: Path) -> "Config":
        path = root / CONFIG_NAME
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise LedgerError(f"{path} isn't valid json: {e}")
        return cls(root=root, data=_merge(DEFAULTS, raw))

    def __getitem__(self, k):
        return self.data[k]

    # getters for standard properties
    @property
    def params_dir(self) -> Path:
        return self.root / self.data["params_dir"]

    @property
    def main(self) -> str:  # gets the git branch name
        return self.data["main_branch"]

    @property
    def disciplines(self) -> dict:
        return self.data["disciplines"]

    # which discipline a script belongs to from the folders in ledger.json
    def discipline_for_path(self, rel_path: str) -> str | None:
        rel = rel_path.replace("\\", "/")  # cuz we have windows and mac users
        best, best_len = None, -1

        # each discipline is a dict
        for name, d in self.disciplines.items():
            for folder in d.get("folders", []):
                # deals with any stray "/"
                folder = folder.strip("/")

                # takes the longest matching folder, so a path under
                # both "src" and "src/aero" resolves to "src/aero"
                if (rel == folder or rel.startswith(folder + "/")) and len(
                    folder
                ) > best_len:
                    best, best_len = name, len(folder)

        return best

    # just extracts the owners from a given discipline
    def owners(self, discipline: str) -> list[str]:
        return list(self.disciplines.get(discipline, {}).get("owners", []))
