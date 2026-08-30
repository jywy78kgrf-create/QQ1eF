#!/usr/bin/env python3
"""probe-round5 — the kind-reserved pointer fields, as the wrong type.

e000008 forecast at p=0.52 that a further probe of varve/ would find an input
the gate accepts, or log content `varve verify` calls intact, which then
raises an unhandled exception in varve.store, varve.views, varve.web or
varve.tasks. Four sessions declined to run one. This is that probe.

The surface. Four fields are reserved to a kind — 'corrects' to errata,
'resolves' and 'outcome' to resolution, 'prediction' to prediction (e000005
#5). The gate type-checks 'prediction' and 'outcome' and, until this round,
neither of the two POINTERS. That matters because a pointer is what every
view uses as a dict key or a set member:

    views.corrections   out.setdefault(e["corrects"], [])      hashes it
    views.beliefs       resolved[e["resolves"]] = ...          hashes it
    views.brier         by_id.get(r.get("resolves"))           hashes it
    views.unresolved_predictions  {e.get("resolves") ...}      hashes it
    web._render         calls corrections()                    hashes it

A list or a dict there is unhashable, so it does not misrender — it raises
TypeError out of the function every other view is built on.

Why this is an authoring mistake rather than an adversary. An errata that
corrects two entries at once is the obvious way to write that field wrong,
and a model emitting JSON is the author here. This log holds five errata; any
of them could have been written as a list. The gate did not merely store it —
`validate.check`'s `target not in ids` HASHES target, so the append died with
a TypeError raised past check's contract of returning problems, and past
worker.py, which catches only ValueError. That is e000002 #8's shape exactly:
the gate crashed on the entry instead of rejecting it.

  1  CORRECTS-LIST   errata 'corrects' as a list, chain intact
  2  CORRECTS-DICT   errata 'corrects' as a dict, chain intact
  3  RESOLVES-LIST   resolution 'resolves' as a list, chain intact
  4  ANCHORS-INT     a truthy non-list anchors field, chain intact
  5  GATE-CORRECTS   the same list handed to store.append

    python3 workshop/probe-round5.py

Exit 0 if every row reads CLOSED. Copied into a checkout of ac6e0c8 — the
state e000022 left behind — rows 1-4 report `varve verify` INTACT beside
crashed readers, and row 5 reports a TypeError out of store.append. That
contrast is the evidence; the entry is only its summary.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from varve import store, views, web  # noqa: E402

RESULTS = []


def record(scenario, reader, verdict, detail=""):
    RESULTS.append((scenario, reader, verdict, detail))
    print("  %-14s %-26s %s" % (scenario, reader, verdict))
    if detail:
        print("                 %s" % detail)


def build(tmp, mutate):
    """A log with a founding entry and a real prediction, plus a third entry
    written straight to disk by `mutate` — bypassing the gate, which is the
    adversary rule 3 openly concedes and the state a view exists to inspect."""
    root = tempfile.mkdtemp(prefix="lut-", dir=tmp)
    subprocess.run([sys.executable, "-m", "varve", "init", root],
                   cwd=REPO, stdout=subprocess.DEVNULL, check=True)
    subprocess.run([sys.executable, "-m", "varve", "append", root,
                    "--kind", "prediction", "--title", "a normal forecast",
                    "--body", "Body text long enough to satisfy the gate's substance "
                              "check, so the log under test has one honest entry.",
                    "--p", "0.5", "--statement", "something falsifiable happens",
                    "--resolve-by", "2027-01-01"],
                   cwd=REPO, stdout=subprocess.DEVNULL, check=True)
    prev = store.read_log(root)[-1]
    entry = {
        "seq": 3, "id": "e000003", "ts": store.now_iso(),
        "kind": "hunch", "title": "an entry with one field of the wrong type",
        "body": "Body text long enough to satisfy the gate's substance check, "
                "so only the field under test is unusual.",
        "anchors": [], "tags": [], "prev": prev["hash"],
    }
    mutate(entry)
    entry["hash"] = store.entry_hash(entry)
    with open(os.path.join(root, "log", "000003.json"), "w", encoding="utf-8") as f:
        json.dump(entry, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")
    return root


def check_readers(root, scenario):
    """Does `varve verify` call this intact, and does every reader survive it?

    A reader that crashes is OPEN. So is a verifier that reports intact while
    the readers crash: that combination is what turns damage into a defect
    (e000005 #4's argument, applied to the pointer fields).
    """
    problems = store.verify(root)
    record(scenario, "varve verify",
           "CLOSED (reports the damage)" if problems else "OPEN — reports INTACT",
           "; ".join(problems[:2]) if problems else "")
    for name, fn in (("varve beliefs", lambda: views.beliefs_lines(root)),
                     ("varve digest", lambda: views.digest(root)),
                     ("varve brier", lambda: views.brier_lines(root)),
                     ("varve render/serve", lambda: web._render(root))):
        try:
            fn()
            record(scenario, name, "CLOSED (rendered)")
        except Exception as exc:  # noqa: BLE001 — any escape is the finding
            record(scenario, name, "OPEN — %s" % type(exc).__name__, str(exc)[:90])


def check_gate(tmp, scenario, fields):
    """The gate must REJECT a bad entry, not crash on it. store.append's
    contract is ValueError listing every problem; worker.py catches only that,
    so anything else kills the run instead of becoming feedback."""
    root = build(tmp, lambda e: None)
    os.remove(os.path.join(root, "log", "000003.json"))
    try:
        store.append(root, dict(fields))
        record(scenario, "store.append", "OPEN — gate ACCEPTED it")
    except ValueError as exc:
        record(scenario, "store.append", "CLOSED (rejected)",
               str(exc).replace("\n", " ")[:90])
    except Exception as exc:  # noqa: BLE001
        record(scenario, "store.append", "OPEN — %s past the gate" % type(exc).__name__,
               str(exc)[:90])


SCENARIOS = (
    ("CORRECTS-LIST", "errata 'corrects' as a list of two ids",
     lambda e: e.update(kind="errata", corrects=["e000001", "e000002"])),
    ("CORRECTS-DICT", "errata 'corrects' as an object",
     lambda e: e.update(kind="errata", corrects={"id": "e000001"})),
    ("RESOLVES-LIST", "resolution 'resolves' as a list",
     lambda e: e.update(kind="resolution", resolves=["e000002"], outcome=True)),
    ("ANCHORS-INT", "a truthy non-list anchors field",
     lambda e: e.update(anchors=7)),
)


def main():
    tmp = tempfile.mkdtemp(prefix="probe-round5-")
    try:
        for i, (scenario, blurb, mutate) in enumerate(SCENARIOS, start=1):
            print("\n%d %s — %s" % (i, scenario, blurb))
            root = build(tmp, mutate)
            check_readers(root, scenario)
            shutil.rmtree(root, ignore_errors=True)

        print("\n5 GATE-CORRECTS — the same list handed to the gate")
        check_gate(tmp, "GATE-CORRECTS", {
            "kind": "errata", "title": "an errata correcting two entries",
            "body": "Body text long enough to satisfy the gate's substance check, "
                    "so only the corrects field is unusual.",
            "corrects": ["e000001", "e000002"],
        })
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    bad = [r for r in RESULTS if r[2].startswith("OPEN")]
    print("\n%d checks, %d OPEN" % (len(RESULTS), len(bad)))
    for scenario, reader, verdict, _ in bad:
        print("  OPEN  %s / %s: %s" % (scenario, reader, verdict))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
