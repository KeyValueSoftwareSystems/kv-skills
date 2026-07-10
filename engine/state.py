"""Per-feature run ledger: .maestro/<slug>/state.yaml.

Only engine code writes this file — the lead agent never edits it (LLMs corrupt
hand-edited state). Writes go through an fcntl lock plus tmp+rename, both carried over
from the v1 workflows/state.py. A corrupt ledger fails soft: treated as absent, with a
warning on stderr, so a damaged file never bricks a run.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import hashlib
import os
import sys

try:
    import fcntl
except ImportError:  # non-POSIX fallback: locking becomes a no-op
    fcntl = None

try:
    import wf
except ImportError:  # imported as part of a package (tests)
    from . import wf

MAESTRO_DIR = ".maestro"
STATE_VERSION = 1


def feature_dir(slug, root="."):
    return os.path.join(root, MAESTRO_DIR, slug)


def state_path(slug, root="."):
    return os.path.join(feature_dir(slug, root), "state.yaml")


def now_iso():
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def artifact_ok(path, root="."):
    full = path if os.path.isabs(path) else os.path.join(root, path)
    try:
        return os.path.getsize(full) > 0
    except OSError:
        return False


def new_state(slug, workflow_file, workflow_hash, inputs):
    return {
        "version": STATE_VERSION,
        "slug": slug,
        "workflow": {"file": workflow_file, "sha256": workflow_hash},
        "frames": {},  # path -> {workflow, sha256, inputs} for entered subworkflows
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "inputs": inputs,
        "run": {"status": "running", "cursors": []},
        "steps": {},
        "gates": [],
    }


def step_entry(state, path):
    entry = state["steps"].get(path)
    if entry is None:
        entry = {"status": "pending", "attempts": 0, "visits": 0, "outputs": {}}
        state["steps"][path] = entry
    return entry


def load(slug, root="."):
    """Read-only load. Returns None if absent; corrupt files fail soft to None."""
    path = state_path(slug, root)
    if not os.path.exists(path):
        return None
    try:
        data = wf.load_file(path)
    except (wf.WfError, OSError) as exc:
        print(f"warning: corrupt state file {path}: {exc}", file=sys.stderr)
        return None
    if not isinstance(data, dict) or data.get("version") != STATE_VERSION:
        print(f"warning: unsupported state file {path}; ignoring it", file=sys.stderr)
        return None
    return data


def save(slug, state, root="."):
    state["updated_at"] = now_iso()
    path = state_path(slug, root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    wf.dump_file(path, state)


@contextlib.contextmanager
def locked(slug, root="."):
    """Exclusive lock around a read-modify-write of the ledger."""
    directory = feature_dir(slug, root)
    os.makedirs(directory, exist_ok=True)
    lock_file = os.path.join(directory, "state.yaml.lock")
    fh = open(lock_file, "a+")
    try:
        if fcntl is not None:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        if fcntl is not None:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()
