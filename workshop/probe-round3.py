#!/usr/bin/env python3
"""Third-round probe of a varve checkout: the surface e000002 listed as untested.

e000002 closed eight defects and ended by naming what it had NOT probed —
unicode and control characters, duplicate JSON keys, unknown extra fields,
concurrent appends, the CLI surface. e000004 then forecast at p=0.65 that a
further probe would find at least one more input of the same class. This
script is that probe, kept here so the finding is reproducible rather than
merely reported.

    python workshop/probe-round3.py

Same contract as workshop/gate-probe.py: each probe is OPEN if the defect is
present, CLOSED if the fix holds, CRASH if the probe itself failed in a way it
did not anticipate — which is also a finding. Against the commit that fixed
these, all nine read CLOSED; against 14bd029 (the state e000002 left behind)
all nine read OPEN. That contrast is the evidence.

The two probes worth reading first are `write_race_forges_an_entry`, which
needs no adversary and no malformed input at all, and
`surrogate_passes_the_gate`, which is defect 8 of e000002 reopened through a
mismatch between how the gate serialises an entry and how the writer does.
"""

import json
import os
import shutil
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from varve import store, views, web  # noqa: E402


def fresh():
    d = tempfile.mkdtemp(prefix="varve-probe3-")
    store.init(d, note="probe")
    return d


def probe(fn):
    d = fresh()
    try:
        return fn(d)
    except Exception as exc:  # a probe should never fall over on its own
        return "CRASH", "%s: %s" % (type(exc).__name__, exc)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _forge(d, mutate):
    """Append a normal entry, then edit it on disk and re-hash so the chain
    still walks. This is the 'writer holds the disk' case the chain concedes
    it cannot catch — but verify() calling the result INTACT is what turns a
    consumer crash into a defect rather than expected behaviour."""
    store.append(d, {"kind": "hunch", "title": "t", "body": "b"})
    p = os.path.join(d, "log", "000002.json")
    with open(p, encoding="utf-8") as f:
        e = json.load(f)
    mutate(e)
    e["hash"] = store.entry_hash(e)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(e, f, indent=1, sort_keys=True)


def _consumers(d):
    """Every read path a stranger would reach for, in the order they'd try."""
    return (("store.append", lambda: store.append(d, {"kind": "hunch", "title": "x", "body": "y"})),
            ("views.beliefs", lambda: views.beliefs(d)),
            ("views.brier", lambda: views.brier(d)),
            ("views.digest", lambda: views.digest(d, days=3650)),
            ("web._render", lambda: web._render(d)))


def _first_crash(d, skip=()):
    for name, call in _consumers(d):
        if name in skip:
            continue
        try:
            call()
        except ValueError as exc:
            # A ValueError out of store.append is the gate refusing, which is a
            # decision. Out of a READ path it is a crash — views.digest raises
            # ValueError from strptime, and an earlier draft of this probe
            # scored that CLOSED by treating every ValueError alike.
            if name == "store.append":
                continue
            return "%s raised ValueError: %s" % (name, str(exc)[:60])
        except Exception as exc:
            return "%s raised %s" % (name, type(exc).__name__)
    return None


# --- the nine defects found on 2026-08-24 -----------------------------------

def write_race_forges_an_entry(d):
    """Concurrent appends share one tmp path.

    store._write writes to '<path>.tmp' — a name derived only from the
    sequence number, so every writer racing for the same seq opens the SAME
    file. json.dump writes incrementally, so two writers interleave into one
    file that still parses: sort_keys means both emit keys in the same order,
    and the result is a well-formed entry carrying one author's title beside
    another author's body, under a hash that covers neither.

    No adversary, no malformed input, no disk access beyond what an ordinary
    append already has. And under rule 1 the resulting entry cannot be removed,
    so the chain is broken permanently.
    """
    shutil.rmtree(d, ignore_errors=True)
    for _ in range(20):
        t = fresh()
        try:
            def w(i):
                try:
                    store.append(t, {"kind": "hunch", "title": "writer-%d" % i,
                                     "body": ("%d" % i) * 300000})
                except Exception:
                    pass  # losing the race is fine; corrupting the log is not
            threads = [threading.Thread(target=w, args=(i,)) for i in range(8)]
            for th in threads:
                th.start()
            for th in threads:
                th.join()
            problems = store.verify(t)
            if problems:
                return "OPEN", "chain broken with no tamper: %s" % problems[0]
        finally:
            shutil.rmtree(t, ignore_errors=True)
    os.makedirs(os.path.join(d, "log"), exist_ok=True)  # keep the caller's rmtree happy
    return "CLOSED", "20 racing trials, chain intact every time"


def surrogate_passes_the_gate(d):
    """The gate's serialisability check does not match the write path.

    validate.check calls json.dumps(entry) with the default ensure_ascii=True,
    which happily escapes a lone surrogate to '\\ud800'. store.canonical uses
    ensure_ascii=False and entry_hash then calls .encode('utf-8'), which
    refuses surrogates. So the gate certifies an entry the writer cannot write,
    and the append dies past the gate with UnicodeEncodeError — which
    worker.py, catching only ValueError, does not handle. This is defect 8 of
    e000002 reopened: the check was added, but not against the operation it
    was checking.
    """
    try:
        store.append(d, {"kind": "hunch", "title": "lone \ud800 surrogate", "body": "b"})
        return "OPEN", "entry with a lone surrogate accepted and written"
    except UnicodeEncodeError:
        return "OPEN", "raised UnicodeEncodeError past the gate"
    except ValueError as exc:
        if isinstance(exc, UnicodeEncodeError):  # UnicodeEncodeError IS a ValueError
            return "OPEN", "raised UnicodeEncodeError past the gate"
        return "CLOSED", "rejected at the gate"


def missing_id_verifies_intact(d):
    """verify() never checks that an entry has an id, but every consumer keys
    on one. An entry with no 'id' walks the chain cleanly and then raises
    KeyError out of store, views and web alike — including the gate, which
    builds its id set with e['id'] and so cannot even reject the next append.
    Defect 6 of e000002 taught views to read 'kind' defensively; 'id' was left
    as a subscript in the same functions."""
    _forge(d, lambda e: e.pop("id", None))
    if store.verify(d):
        return "CLOSED", "verify reports the missing id"
    crash = _first_crash(d)
    return ("OPEN", crash) if crash else ("CLOSED", "no consumer crashes")


def impossible_date_verifies_intact(d):
    """TS_RE checks the SHAPE of a timestamp, not that it names a day.
    '2026-13-45T99:99:99Z' full-matches the regex, sorts after its predecessor,
    and so passes both the gate's monotonicity test and verify(). views.digest
    then calls strptime on it and raises ValueError."""
    _forge(d, lambda e: e.__setitem__("ts", "2026-13-45T99:99:99Z"))
    if store.verify(d):
        return "CLOSED", "verify reports the impossible date"
    crash = _first_crash(d, skip=("store.append",))  # append refuses on ts order, correctly
    return ("OPEN", crash) if crash else ("CLOSED", "no consumer crashes")


def verify_crashes_on_non_object_entry(d):
    """A file in log/ that is valid JSON but not an object — '[1,2,3]', or a
    bare string — makes verify() raise AttributeError on its first .get().

    This is the defect e000002 #3 said it had closed: 'a verifier that crashes
    on a damaged log has failed at its only job, which is diagnosis'. The fix
    type-checked the ts FIELD; it did not type-check the entry."""
    with open(os.path.join(d, "log", "000002.json"), "w", encoding="utf-8") as f:
        f.write("[1, 2, 3]\n")
    try:
        problems = store.verify(d)
    except Exception as exc:
        return "OPEN", "verify raised %s" % type(exc).__name__
    if any("000002.json" in p for p in problems):
        return "CLOSED", "reported, naming the file"
    return "OPEN", "not reported: %s" % problems


def duplicate_keys_diverge(d):
    """JSON permits duplicate keys and json.load silently keeps the LAST.

    So an entry file can carry two 'body' values: a human opening
    log/000002.json reads the first, while json.load — and therefore
    entry_hash, verify, and every view — sees only the second. verify calls it
    intact, because it IS intact with respect to the value it can see.

    This matters more here than in an ordinary store. The chain's promise is
    that the bytes on disk and the record are the same thing; a reader
    auditing the raw files is exactly the reader rule 5 exists to serve."""
    store.append(d, {"kind": "hunch", "title": "t", "body": "SECOND"})
    p = os.path.join(d, "log", "000002.json")
    with open(p, encoding="utf-8") as f:
        e = json.load(f)
    raw = json.dumps(e, indent=1, sort_keys=True).replace(
        '"body": "SECOND"', '"body": "FIRST",\n "body": "SECOND"', 1)
    with open(p, "w", encoding="utf-8") as f:
        f.write(raw)
    try:
        problems = store.verify(d)
    except Exception as exc:
        return "OPEN", "verify raised %s" % type(exc).__name__
    if problems:
        return "CLOSED", "reported: %s" % problems[0]
    with open(p, encoding="utf-8") as f:
        seen = json.load(f)["body"]
    return "OPEN", "raw file shows FIRST, chain covers %r, verify says intact" % seen


def control_chars_forge_the_digest(d):
    """The gate accepts any non-empty string as a title, including one
    containing a newline and an ANSI erase-line sequence. views.digest prints
    'id ts [kind] title' one entry per line, so such a title renders as extra
    lines that read exactly like further log entries — a fabricated
    observation, in a view of a log whose whole premise is that its author
    cannot fabricate history.

    Rules 1-4 are untouched here. The forgery is in the READING, which is
    rule 6's territory and which the chain does not defend."""
    forged = "benign\n\x1b[2Ke000099 2026-01-01 [observation] FABRICATED"
    try:
        store.append(d, {"kind": "hunch", "title": forged, "body": "b"})
    except ValueError:
        return "CLOSED", "rejected at the gate"
    out = views.digest(d, days=3650)
    if "FABRICATED" in out and "\x1b" in out:
        return "OPEN", "digest renders a fabricated entry line verbatim"
    return "CLOSED", "control characters neutralised in the view"


def resolution_fields_unreserved(d):
    """The gate reserves 'corrects' to kind errata — and reserves nothing else.

    So a hunch may carry 'resolves', 'outcome' and 'prediction' all at once.
    Nothing reads them, because every view filters on kind; a human reading
    the entry, or the raw JSON, sees what looks like a resolution of e000001.
    The machinery and the reader disagree about what the entry is, which is
    the one thing rule 6 asks an entry not to do."""
    try:
        store.append(d, {"kind": "hunch", "title": "t", "body": "b",
                         "resolves": "e000001", "outcome": True,
                         "prediction": {"statement": "s", "p": 0.9,
                                        "resolve_by": "2030-01-01"}})
        return "OPEN", "hunch stored carrying resolves/outcome/prediction"
    except ValueError:
        return "CLOSED", "rejected at the gate"


def falsy_anchors_bypass_the_type_check(d):
    """validate.check reads `entry.get("anchors") or []` and then type-checks
    the RESULT, so any falsy non-list — 0, {}, "", False — is replaced by []
    before the 'anchors must be a list' test ever sees it. The entry is then
    stored with anchors as an integer. Small, but it is the same shape as
    every defect in e000002: the gate judged the coerced value, not the field."""
    try:
        e = store.append(d, {"kind": "hunch", "title": "t", "body": "b", "anchors": 0})
    except ValueError:
        return "CLOSED", "rejected at the gate"
    if isinstance(e.get("anchors"), list):
        return "CLOSED", "coerced; stored %r" % (e.get("anchors"),)
    return "OPEN", "stored anchors=%r (%s)" % (e["anchors"], type(e["anchors"]).__name__)


PROBES = [
    ("concurrent appends forge an entry", write_race_forges_an_entry),
    ("lone surrogate passes the gate", surrogate_passes_the_gate),
    ("missing id verifies intact", missing_id_verifies_intact),
    ("impossible date verifies intact", impossible_date_verifies_intact),
    ("verify crashes on a non-object entry", verify_crashes_on_non_object_entry),
    ("duplicate JSON keys diverge from the chain", duplicate_keys_diverge),
    ("control characters forge the digest", control_chars_forge_the_digest),
    ("resolution fields unreserved", resolution_fields_unreserved),
    ("falsy anchors bypass the type check", falsy_anchors_bypass_the_type_check),
]


def main():
    width = max(len(n) for n, _ in PROBES)
    states = []
    for name, fn in PROBES:
        state, detail = probe(fn)
        states.append(state)
        print("  %-*s  %-6s  %s" % (width, name, state, detail))
    print()
    open_count = states.count("OPEN") + states.count("CRASH")
    print("%d of %d probes report a defect present." % (open_count, len(PROBES)))
    return 1 if open_count else 0


if __name__ == "__main__":
    print("varve round-3 probe — %s\n" % os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    sys.exit(main())
