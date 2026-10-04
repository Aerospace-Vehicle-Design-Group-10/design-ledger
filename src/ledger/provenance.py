"""tracks who called the lib, and fingerprints the script"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import sysconfig
from pathlib import Path

# the directory we are in
_PKG_DIR = Path(__file__).resolve().parent
# plus a separator
_PKG_PREFIX = str(_PKG_DIR) + os.sep

# want to ignore std files so need this
_STDLIB = str(Path(sysconfig.get_paths()["stdlib"]).resolve()) + os.sep


def file_hash(path: Path) -> str:
    # git's blob hash of the file (apparently we need to CRLF normalize so
    # that win and mac agree)
    data = Path(path).read_bytes()
    if b"\0" not in data:
        data = data.replace(b"\r\n", b"\n")
    # and then just a normal sha hash
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


# first file on the stack that isn't part of the ledger package or the standard lib
def caller_file() -> Path | None:
    # grabs the callers frame (which is one up from this file)
    frame = sys._getframe(1)

    # we just walk up the caller chain
    while frame is not None:
        frame_name = frame.f_code.co_filename  # the filename this frames code is from
        # go up a level for the next loop
        frame = frame.f_back

        # skips frames without a filename or a synthetic one
        if not frame_name or frame_name.startswith("<"):
            continue

        # resolves symlinks (in case there are any)
        real = os.path.realpath(frame_name) if frame_name else frame_name

        # we skip frames that are in this package or in the standard lib
        if real.startswith(_PKG_PREFIX) or real.startswith(_STDLIB):
            continue
        # neither of these are supported so just returns
        if "ipykernel" in frame_name or "IPython" in frame_name:
            return None
        p = Path(frame_name)
        return p.resolve() if p.is_file() else None
    return None


# returns the relative version of a path from root
def rel_to(root: Path, path: Path) -> str | None:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None


# for tracking who stuff is from, just need a username so either git or env is fine
def git_user(root: Path) -> str:
    try:
        name = subprocess.run(
            ["git", "config", "user.name"], cwd=root, capture_output=True, text=True
        ).stdout.strip()
    except OSError:
        # its not critical so may as well just let it happen
        name = ""
    return name or os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"
