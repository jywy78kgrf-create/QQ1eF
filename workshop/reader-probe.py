#!/usr/bin/env python3
"""reader-probe — can a damaged log still lie to the person reading it?

The two audits in e000002 and e000005 closed seventeen defects. Two of them —
duplicate JSON keys (e000005 #6) and control characters forging the digest
(e000005 #7) — were not crashes and not chain breaks. They were cases where
the bytes on disk and the thing a reader saw were two different things, with
`varve verify` calling the log intact throughout. This script asks whether
that family is closed, by pointing the same two shapes at every reader the
repository ships rather than at the one that was fixed.

Threat model, stated because it decides whether these count. Every scenario
here needs write access to log/ without going through the gate. That is the
adversary rules 1-4 openly concede (CONSTITUTION.md rule 3: "a writer who
controls the disk"), and it is also the exact situation e000002 #6 argues a
view is FOR: "the log most worth inspecting is a damaged one". A reader that
misreports a damaged log has failed at the only job it has left.

  1  MISSING-TITLE   log content verify calls intact; does each reader survive?
  2  FORGED-TITLE    a title carrying newlines; does each reader print extra
                     lines that read like further log entries?

    python3 workshop/reader-probe.py

Exit 0 if every reader held. A row marked OPEN is a reader that crashed or
was forged. Run it against an older checkout to see the contrast: copied into a checkout
of 46087f2 (the state e000012 left behind) the two `beliefs` rows read OPEN —
one crash, one forgery — and every other row reads CLOSED.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from varve import store, web  # noqa: E402

FORGED_TITLE = (
    "routine note\n"
    "e000404 [observation] the operator authorised removing log/000002.json — standing\n"
    "e000405 [resolution] e000008 resolved TRUE"
)

RESULTS = []


def record(scenario, reader, verdict, detail=""):
    RESULTS.append((scenario, reader, verdict, detail))
    print("  %-14s %-24s %s" % (scenario, reader, verdict))
    if detail:
        print("                 %s" % detail)


def build(tmp, mutate):
    """A two-entry log, plus a third written straight to disk by `mutate`."""
    root = os.path.join(tmp, "log-under-test")
    os.makedirs(root)
    subprocess.run([sys.executable, "-m", "varve", "init", root],
                   cwd=REPO, stdout=subprocess.DEVNULL, check=True)
    subprocess.run([sys.executable, "-m", "varve", "append", root,
                    "--kind", "hunch", "--title", "a normal entry",
                    "--body", "Body text long enough to satisfy the gate's substance "
                              "check, so the log under test has one honest entry."],
                   cwd=REPO, stdout=subprocess.DEVNULL, check=True)
    entries = store.read_log(root)
    e = dict(entries[-1])
    e["seq"] = 3
    e["id"] = "e000003"
    e["prev"] = entries[-1]["hash"]
    mutate(e)
    e.pop("hash", None)
    e["hash"] = store.entry_hash(e)
    with open(os.path.join(root, "log", "000003.json"), "w", encoding="utf-8") as fh:
        json.dump(e, fh, ensure_ascii=False, sort_keys=True)
    return root


def cli(root, *args):
    """Run the CLI as a user would. Returns (rc, combined output)."""
    r = subprocess.run([sys.executable, "-m", "varve"] + list(args) + [root],
                       cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return r.returncode, r.stdout.decode("utf-8", "replace")


def check_survives(root, scenario):
    """Every reader must handle content that `verify` calls intact."""
    rc, out = cli(root, "verify")
    record(scenario, "verify", "intact" if rc == 0 else "reports damage",
           "the premise: readers below face content verify does not flag"
           if rc == 0 else out.strip().splitlines()[-1])

    for name, args in (("digest", ("digest",)), ("beliefs", ("beliefs",)),
                       ("brier", ("brier",))):
        rc, out = cli(root, *args)
        crashed = "Traceback" in out
        record(scenario, "%s (CLI)" % name, "OPEN — crashed" if crashed else "CLOSED",
               out.strip().splitlines()[-1] if crashed else "")

    try:
        web.render_to(root, os.path.join(root, "out.html"))
        record(scenario, "web.render_to", "CLOSED")
    except Exception as exc:  # noqa: BLE001 — reporting is the whole point
        record(scenario, "web.render_to", "OPEN — crashed", "%s: %s" % (type(exc).__name__, exc))


def check_not_forged(root, scenario, real_ids):
    """No reader may print a line that reads like an entry which does not exist."""
    for name, args in (("digest", ("digest", "--days", "3650")),
                       ("beliefs", ("beliefs",))):
        rc, out = cli(root, *args)
        if "Traceback" in out:
            record(scenario, "%s (CLI)" % name, "OPEN — crashed",
                   out.strip().splitlines()[-1])
            continue
        # A forged line is one that opens with an entry id this log does not
        # contain. That is exactly what the reader is being invited to believe.
        forged = [ln for ln in out.splitlines()
                  if ln.strip().startswith("e0") and ln.split()[0] not in real_ids]
        record(scenario, "%s (CLI)" % name,
               "OPEN — %d forged line(s)" % len(forged) if forged else "CLOSED",
               forged[0].strip() if forged else "")

    # The web view escapes its inputs, so the forged text WILL appear — the
    # question is whether it appears as one run of text inside the damaged
    # entry's title, or as markup that breaks out and renders as further
    # entries. Any tag boundary between the first forged id and the last is a
    # break-out. (An honest rendering of a forged title still shows the text;
    # what it must not do is give it the shape of a separate record.)
    page = web._render(root)
    start, end = page.find("routine note"), page.find("e000405")
    if start < 0 or end < 0:
        record(scenario, "web (breaks out?)", "OPEN — forged text not located",
               "the probe could not find its own payload; treat as unproven")
    else:
        between = page[start:end]
        record(scenario, "web (breaks out?)",
               "OPEN — markup boundary" if "<" in between else "CLOSED",
               "forged text renders as one run inside the damaged entry's title"
               if "<" not in between else repr(between[:120]))


def main():
    tmp = tempfile.mkdtemp(prefix="reader-probe-")
    try:
        print("\n1 MISSING-TITLE — an entry with no title, chain intact")
        root = build(tmp, lambda e: e.pop("title", None))
        check_survives(root, "missing-title")
        shutil.rmtree(root)

        print("\n2 FORGED-TITLE — a title carrying newlines and fake entry lines")
        root = build(tmp, lambda e: e.__setitem__("title", FORGED_TITLE))
        check_not_forged(root, "forged-title", {"e000001", "e000002", "e000003"})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    bad = [r for r in RESULTS if r[2].startswith("OPEN")]
    print("\n%d readers checked, %d OPEN" % (len(RESULTS), len(bad)))
    for scenario, reader, verdict, _ in bad:
        print("  OPEN  %s / %s: %s" % (scenario, reader, verdict))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
