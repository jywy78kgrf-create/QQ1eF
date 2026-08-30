"""The log: append-only entries, hash-chained, founded empty.

Entries live as one JSON file per entry under <root>/log/, named by sequence
number. The file layout is the canonical store; anything else (indexes, views,
dashboards) must be derivable from it. An entry's hash covers its full content
including the previous entry's hash, so any historical edit breaks the chain
from that point on — that property, not trust in this code, is the guarantee.
"""

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone

from . import validate

LOG_DIR = "log"
# 6+ digits: %06d widens past 999999 on its own, but a fixed {6} regex would
# silently DROP entry one million from read_log — a truncation bug wearing a
# filename convention as a disguise (first external review, 2026-08-22).
_SEQ_RE = re.compile(r"^(\d{6,})\.json$")


def _log_dir(root):
    return os.path.join(root, LOG_DIR)


def _entry_path(root, seq):
    return os.path.join(_log_dir(root), "%06d.json" % seq)


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical(entry):
    """The byte string an entry's hash covers: everything except 'hash' itself."""
    body = {k: v for k, v in entry.items() if k != "hash"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def entry_hash(entry):
    return hashlib.sha256(canonical(entry).encode("utf-8")).hexdigest()


def _reject_duplicate_keys(pairs):
    """json.load's object hook, refusing objects with a repeated key.

    JSON permits duplicates and every mainstream parser silently keeps the
    last. Here that splits the record in two: a human auditing log/000002.json
    reads the FIRST "body", while json.load — and so entry_hash, verify, and
    every view — sees only the second, and calls the file intact. The chain's
    whole promise is that the bytes on disk and the record are one thing, and
    rule 5 exists precisely to send strangers to those bytes (third review,
    2026-08-24).
    """
    seen = set()
    for k, _ in pairs:
        if k in seen:
            raise ValueError("duplicate JSON key %r — the file says two things "
                             "and the chain can only cover one" % k)
        seen.add(k)
    return dict(pairs)


def read_log(root):
    """All entries in sequence order. Missing dir means no log here."""
    d = _log_dir(root)
    if not os.path.isdir(d):
        raise FileNotFoundError("no varve log at %s (run: varve init)" % root)
    found = []
    for name in os.listdir(d):
        m = _SEQ_RE.match(name)
        if m:
            found.append((int(m.group(1)), name))
    entries = []
    # numeric sort, not lexicographic: "1000000.json" sorts before "999999.json"
    # as a string, which would shuffle the chain right when the log gets long
    for _, name in sorted(found):
        path = os.path.join(d, name)
        rel = os.path.join(LOG_DIR, name)
        with open(path, "r", encoding="utf-8") as f:
            try:
                entry = json.load(f, object_pairs_hook=_reject_duplicate_keys)
            except ValueError as exc:
                # Name the file. An unreadable entry IS a broken chain, and the
                # reader needs to know which one — a bare JSONDecodeError points
                # at a column of a file it never names (second review,
                # 2026-08-23). JSONDecodeError is a ValueError, and so is the
                # duplicate-key refusal above; both are the same failure to a
                # reader, which is "this file is not a readable entry".
                raise ValueError("%s is not a readable entry: %s" % (rel, exc)) from exc
        if not isinstance(entry, dict):
            # '[1,2,3]' or a bare string parses fine and then makes every
            # .get() in verify() raise AttributeError. e000002 #3 type-checked
            # the ts FIELD on the reasoning that a verifier which crashes on a
            # damaged log has failed at its only job; it did not type-check the
            # entry (third review, 2026-08-24).
            raise ValueError("%s is not a readable entry: expected a JSON object, got %s"
                             % (rel, type(entry).__name__))
        entries.append(entry)
    return entries


def init(root, note=""):
    """Found a log. Refuses to found over an existing one — a second founding
    is exactly the kind of history rewrite the constitution forbids."""
    d = _log_dir(root)
    if os.path.isdir(d) and any(_SEQ_RE.match(n) for n in os.listdir(d)):
        raise ValueError("a varve log already exists at %s" % root)
    os.makedirs(d, exist_ok=True)
    founding = {
        "seq": 1,
        "id": "e000001",
        "ts": now_iso(),
        "kind": "meta",
        "title": "founding",
        "body": (
            "This log was founded empty at this timestamp. Nothing predates "
            "this entry; any claim of an earlier entry is fabricated. "
            + (note or "")
        ).strip(),
        "anchors": [],
        "tags": ["founding"],
        "prev": "",
    }
    founding["hash"] = entry_hash(founding)
    _write(root, founding)
    return founding


def append(root, fields):
    """Validate and append one entry. Returns the stored entry.

    Callers supply content fields only; seq/id/prev/hash are assigned here so
    an author can't mint its own position in history. Raises ValueError with
    every gate failure listed — the worker feeds that back to the model.
    """
    entries = read_log(root)
    if not entries:
        raise ValueError("log has no founding entry; refusing to append")
    last = entries[-1]

    entry = dict(fields)
    # 'ts' is reserved along with the rest: a timestamp IS a position in
    # history, and rule 4 (founded empty, time never decreases) rests on it.
    # It used to be a setdefault, so an author could supply its own — and
    # worker.py hands the model's raw JSON straight to this function, making
    # that the untrusted path. A post-dated entry is then permanent: rule 1
    # forbids removing it, and no later entry may carry an earlier timestamp,
    # so one future date jams the log for good (second review, 2026-08-23).
    for reserved in ("seq", "id", "prev", "hash", "ts"):
        entry.pop(reserved, None)
    entry["seq"] = last["seq"] + 1
    entry["id"] = "e%06d" % entry["seq"]
    entry["ts"] = now_iso()
    entry.setdefault("anchors", [])
    entry.setdefault("tags", [])
    entry["prev"] = last["hash"]

    problems = validate.check(entry, entries, root=root)
    if problems:
        raise ValueError("entry rejected by the gate:\n- " + "\n- ".join(problems))

    entry["hash"] = entry_hash(entry)
    _write(root, entry)
    return entry


def _write(root, entry):
    """Write one entry, atomically, without trusting that we are the only writer.

    The previous version derived the scratch name from the sequence number
    alone ('<path>.tmp') and guarded the destination with os.path.exists. Both
    halves failed under concurrency, and the first failed catastrophically:
    every writer racing for the same seq opened the SAME scratch file, and
    since json.dump writes incrementally and sort_keys makes both emit their
    keys in the same order, two writers interleaved into a file that still
    parsed — a well-formed entry carrying one author's title beside another
    author's body, under a hash covering neither. verify() then reported a
    content hash mismatch on an entry nobody had tampered with, and rule 1
    forbids removing it, so the chain was broken permanently. Roughly one in
    three racing trials produced exactly that (third review, 2026-08-24;
    workshop/probe-round3.py).

    So: a scratch name unique to this writer, and the destination claimed with
    os.link, which either creates the name atomically or fails. Content is
    complete before the name exists, so a crash still cannot leave a partial
    entry in the chain — the property the old comment claimed and the old code
    only had while single-threaded.
    """
    path = _entry_path(root, entry["seq"])
    # The '.' prefix and '.tmp' suffix both keep scratch files outside _SEQ_RE,
    # so a crashed writer's leftovers are never read as entries.
    fd, tmp = tempfile.mkstemp(dir=_log_dir(root),
                               prefix=".%06d." % entry["seq"], suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(entry, f, ensure_ascii=False, indent=1, sort_keys=True)
            f.write("\n")
        try:
            os.link(tmp, path)
        except FileExistsError:
            # Someone else took this sequence number between our read_log and
            # now. Their entry is whole and ours was never in the chain; the
            # caller should re-read and retry rather than overwrite.
            raise ValueError(
                "refusing to overwrite %s — another writer took seq %d; "
                "re-read the log and retry" % (path, entry["seq"]))
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def head(root):
    """The chain head: (seq, hash) of the last entry. This is the value to
    witness EXTERNALLY (a session report, a mirror, a transparency log):
    the chain proves internal order, but only a remembered head proves the
    log wasn't truncated or wholesale re-chained by whoever holds the disk."""
    entries = read_log(root)
    if not entries:
        raise ValueError("log is empty")
    return entries[-1]["seq"], entries[-1]["hash"]


def verify(root, expect_head=None):
    """Walk the chain; return a list of problems (empty = intact).

    Honest scope: this detects any PARTIAL tamper — an edited entry, a
    re-hashed edit, a gap, a reordering. It cannot detect tail truncation
    or a full re-chain by the disk's owner; for those, pass expect_head
    (a previously witnessed chain-head hash) or compare `head()` against
    a record the writer doesn't control."""
    try:
        entries = read_log(root)
    except ValueError as exc:
        # An unreadable entry is a verification failure, not an exception for
        # the caller to handle: report it the way every other breakage is
        # reported so `varve verify` prints it and exits 1.
        return [str(exc)]
    problems = []
    if not entries:
        return ["log is empty — not even a founding entry"]
    if entries[0].get("seq") != 1 or entries[0].get("prev") != "":
        problems.append("founding entry malformed (seq!=1 or prev not empty)")
    prev_hash, prev_seq, prev_ts = "", 0, ""
    for e in entries:
        tag = e.get("id", "seq %s" % e.get("seq"))
        # Every field below is read defensively. verify() exists to DIAGNOSE a
        # damaged log, so malformed content must come back as a problem in the
        # list; raising instead turns "your log is broken, here is where" into
        # a traceback (second review, 2026-08-23).
        seq = e.get("seq")
        if not isinstance(seq, int):
            problems.append("%s: malformed seq %r (expected an integer)" % (tag, seq))
        elif seq != prev_seq + 1:
            problems.append("%s: sequence gap (expected %d)" % (tag, prev_seq + 1))
        # An entry with no id walked the chain cleanly here while every
        # consumer — the views, the web page, and the gate's own id set —
        # keyed on e["id"] and raised KeyError. verify() calling that log
        # intact is what made it a defect rather than expected damage
        # (third review, 2026-08-24).
        eid = e.get("id")
        if not isinstance(eid, str) or not re.fullmatch(r"e\d{6,}", eid):
            problems.append("%s: malformed id %r (expected e000123)" % (tag, eid))
        elif isinstance(seq, int) and eid != "e%06d" % seq:
            problems.append("%s: id does not match seq %d" % (tag, seq))
        if e.get("prev", "") != prev_hash:
            problems.append("%s: chain broken (prev hash mismatch)" % tag)
        if entry_hash(e) != e.get("hash"):
            problems.append("%s: content hash mismatch (entry was altered)" % tag)

        # The kind-reserved POINTERS, checked here for the same reason e000005
        # added the id check: every consumer keys on them — corrections() and
        # beliefs() use them as dict keys, unresolved_predictions() puts them
        # in a set — so a non-string one is not cosmetic damage, it is a log
        # no reader can render. verify() calling that intact is what makes it
        # a defect rather than expected damage (fifth review, 2026-08-30).
        for field, owner in (("corrects", "errata"), ("resolves", "resolution")):
            if e.get("kind") == owner and not isinstance(e.get(field), str):
                problems.append("%s: %s entry has malformed '%s' %r (expected an entry id string)"
                                % (tag, owner, field, e.get(field)))
        # anchors is rule 2's evidence field; a non-list one is unreadable to
        # every view that renders provenance.
        if "anchors" in e and not isinstance(e["anchors"], list):
            problems.append("%s: malformed anchors %r (expected a list)" % (tag, e["anchors"]))

        ts = e.get("ts", "")
        # Shape is not enough: '2026-13-45T99:99:99Z' full-matches TS_RE, sorts
        # after its predecessor, and passes every ordering test — then raises
        # ValueError out of views.digest's strptime. A timestamp that names no
        # day cannot order a chain (third review, 2026-08-24).
        if validate.parse_ts(ts) is None:
            problems.append("%s: malformed timestamp %r (expected YYYY-MM-DDThh:mm:ssZ)" % (tag, ts))
        else:
            if prev_ts and ts < prev_ts:
                problems.append("%s: timestamp earlier than predecessor" % tag)
            prev_ts = ts

        prev_hash = e.get("hash", "")
        if isinstance(seq, int):
            prev_seq = seq
    if expect_head and entries and entries[-1].get("hash") != expect_head:
        problems.append(
            "chain head %s… does not match the witnessed head %s… — "
            "truncated tail or forked history" % (entries[-1].get("hash", "")[:12], expect_head[:12])
        )
    return problems
