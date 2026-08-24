"""A small task queue for the resident author.

Tasks are operational state, not memory: they live in <root>/tasks.json, are
mutable, and are explicitly non-canonical — losing this file loses nothing the
log promised to keep. What a task *produced* is in the log, referenced by
entry id on the completed task.
"""

import json
import os
import tempfile

from .store import now_iso

TASK_KINDS = ("research", "reflect", "synthesize", "predict")
_FILE = "tasks.json"


def _path(root):
    return os.path.join(root, _FILE)


def _load(root):
    p = _path(root)
    if not os.path.exists(p):
        return []
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(root, items):
    # A scratch name unique to this writer, for the reason store._write now
    # uses one: a shared '<file>.tmp' lets two concurrent writers interleave
    # their json.dump calls into one file. Here the stakes are far lower —
    # tasks.json is non-canonical and losing it loses nothing the log promised
    # — but the corrupt result would still take every `varve task` and
    # `varve work` run down with a JSONDecodeError until someone deleted it.
    # os.replace, not os.link: this file is meant to be overwritten, so the
    # only property needed is that each writer owns its own scratch
    # (third review, 2026-08-24).
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(_path(root))),
                               prefix="." + _FILE + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=1)
            f.write("\n")
        os.replace(tmp, _path(root))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def add(root, kind, prompt, priority=5):
    if kind not in TASK_KINDS:
        raise ValueError("task kind must be one of: %s" % ", ".join(TASK_KINDS))
    if not prompt.strip():
        raise ValueError("task prompt is required")
    items = _load(root)
    task = {
        "id": "t%06d" % (max((int(t["id"][1:]) for t in items), default=0) + 1),
        "kind": kind,
        "prompt": prompt.strip(),
        "priority": int(priority),
        "status": "pending",
        "created": now_iso(),
    }
    items.append(task)
    _save(root, items)
    return task


def list_tasks(root):
    return _load(root)


def next_pending(root):
    pending = [t for t in _load(root) if t["status"] == "pending"]
    if not pending:
        return None
    # lowest priority number first, then oldest
    return sorted(pending, key=lambda t: (t["priority"], t["created"], t["id"]))[0]


def mark(root, task_id, status, entry_id=None, error=None):
    items = _load(root)
    for t in items:
        if t["id"] == task_id:
            t["status"] = status
            t["finished"] = now_iso()
            if entry_id:
                t["entry_id"] = entry_id
            if error:
                t["error"] = error
            _save(root, items)
            return t
    raise ValueError("no task %s" % task_id)
