#!/usr/bin/env python3
"""rule5-probe — stage the rule 5 failures nobody here has ever staged.

e000011 found a stale remote-tracking ref by accident and reported one
direction of the mechanism: a fossil `origin/main` pointer showed FEWER
entries than existed, producing a false alarm. It named the dangerous
direction explicitly and said it had not staged it — a stale ref would also
hide a force-push or a truncated tail and report the witness healthy.

This script stages it, plus the other rule 5 states, against real git
repositories in a temp directory. Nothing here touches the QQ1eF log; each
scenario builds its own throwaway log with the vendored varve module.

  A  TRUNCATED   the published branch is force-pushed back; local is ahead.
  B  FORKED      the published branch re-chains an entry; hashes diverge.
  C  STALE       (A) again, but read through an unrefreshed origin ref —
                 the direction e000011 reasoned about and did not demonstrate.
  D  LOCAL-STALE the published branch is AHEAD of local. Benign: someone
                 else pushed. witness-check documents this as AHEAD.
  E  DUPLICATE-KEYS a published entry carries the same key twice, so the
                 bytes a stranger reads and the record a parser builds are
                 two different things (the shape of e000005 defect 6).

For each, it reports what workshop/witness-check.py says and what
`varve verify --expect-head <witnessed>` says, because those are the two
instruments this repository owns for rule 5 and neither has a record of
ever being run in anger.

    python3 workshop/rule5-probe.py

Exit status is 0 if every scenario matched its expected verdict, 1 otherwise.
A row marked UNEXPECTED is the interesting output: it means an instrument
that is supposed to catch a rule 5 failure did not.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WITNESS = os.path.join(REPO, "workshop", "witness-check.py")


def git(*args, cwd):
    r = subprocess.run(("git",) + args, cwd=cwd,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if r.returncode != 0:
        raise RuntimeError("git %s failed in %s:\n%s"
                           % (" ".join(args), cwd, r.stdout.decode("utf-8", "replace")))
    return r.stdout.decode("utf-8", "replace")


def varve(*args, cwd):
    """Run the vendored varve CLI. Returns (returncode, output)."""
    env = dict(os.environ, PYTHONPATH=REPO)
    r = subprocess.run((sys.executable, "-m", "varve") + args, cwd=cwd, env=env,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return r.returncode, r.stdout.decode("utf-8", "replace").strip()


def witness(root, extra=()):
    """Run witness-check.py; return (returncode, status_word, full_output)."""
    r = subprocess.run([sys.executable, WITNESS, root] + list(extra),
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = r.stdout.decode("utf-8", "replace")
    status = "?"
    for line in out.splitlines():
        for word in ("OK", "BEHIND", "DIVERGED", "AHEAD"):
            if line.startswith(word + " —") or line.startswith(word + " -"):
                status = word
    return r.returncode, status, out


def head_hash(root):
    rc, out = varve("head", root, cwd=root)
    return out.split()[-1]


def build(tmp, name, n_entries):
    """A bare 'published' repo plus a working clone holding an n-entry log."""
    bare = os.path.join(tmp, name + ".git")
    work = os.path.join(tmp, name)
    git("init", "--bare", "-b", "main", bare, cwd=tmp)
    os.makedirs(work)
    git("init", "-b", "main", work, cwd=tmp)
    git("config", "user.email", "probe@example.invalid", cwd=work)
    git("config", "user.name", "rule5-probe", cwd=work)
    git("remote", "add", "origin", bare, cwd=work)

    varve("init", work, cwd=work)
    for i in range(n_entries):
        rc, out = varve("append", work, "--kind", "hunch",
                        "--title", "probe entry %d" % (i + 1),
                        "--body", "Synthetic entry %d, written by workshop/rule5-probe.py "
                                  "to stage a rule 5 scenario. Not part of any real log." % (i + 1),
                        cwd=work)
        if rc != 0:
            raise RuntimeError("append failed: %s" % out)
    git("add", "-A", cwd=work)
    git("commit", "-m", "log through entry %d" % (n_entries + 1), cwd=work)
    git("push", "-u", "origin", "main", cwd=work)
    return bare, work


def snapshot(work, tmp, name):
    """Copy the worktree aside so a scenario can restore or diverge from it."""
    dst = os.path.join(tmp, name)
    shutil.copytree(work, dst)
    return dst


RESULTS = []


def record(scenario, instrument, expected, got, detail=""):
    ok = expected == got
    RESULTS.append((scenario, instrument, expected, got, ok, detail))
    print("  %-14s %-22s expected %-9s got %-9s %s"
          % (scenario, instrument, expected, got, "ok" if ok else "UNEXPECTED"))
    if detail:
        print("                 %s" % detail)


def scenario_truncated(tmp):
    print("\nA TRUNCATED — published branch force-pushed back two entries")
    bare, work = build(tmp, "trunc", 6)
    witnessed = head_hash(work)

    # The published side loses its tail: a force-push to an earlier commit is
    # the cheapest way for the writer to un-say the last thing they said.
    behind = os.path.join(tmp, "attacker")
    git("clone", bare, behind, cwd=tmp)
    git("config", "user.email", "probe@example.invalid", cwd=behind)
    git("config", "user.name", "rule5-probe", cwd=behind)
    for name in sorted(os.listdir(os.path.join(behind, "log")))[-2:]:
        os.remove(os.path.join(behind, "log", name))
    git("add", "-A", cwd=behind)
    git("commit", "-m", "truncated", cwd=behind)
    git("push", "--force", "origin", "main", cwd=behind)

    rc, status, out = witness(work, ["--ref", "origin/main"])
    record("truncated", "witness-check", "BEHIND", status)

    # And the instrument varve itself ships: verify the PUBLISHED tree against
    # the head a stranger wrote down earlier.
    rc, out = varve("verify", behind, "--expect-head", witnessed, cwd=behind)
    got = "caught" if rc != 0 else "missed"
    record("truncated", "verify --expect-head", "caught", got, out.splitlines()[-1] if out else "")


def scenario_forked(tmp):
    print("\nB FORKED — published branch re-chains one entry and re-pushes")
    bare, work = build(tmp, "fork", 6)
    witnessed = head_hash(work)

    forked = os.path.join(tmp, "forker")
    git("clone", bare, forked, cwd=tmp)
    git("config", "user.email", "probe@example.invalid", cwd=forked)
    git("config", "user.name", "rule5-probe", cwd=forked)
    # Drop the last three entries and write different ones in their place, so
    # the published chain is a valid, fully self-consistent varve chain that
    # simply is not this log's. This is the re-chain the constitution concedes
    # rules 1-4 cannot catch: `varve verify` on the forked tree passes.
    for name in sorted(os.listdir(os.path.join(forked, "log")))[-3:]:
        os.remove(os.path.join(forked, "log", name))
    for i in range(3):
        varve("append", forked, "--kind", "hunch",
              "--title", "substituted entry %d" % (i + 1),
              "--body", "A different entry occupying the same sequence number. "
                        "The published chain verifies; it is simply not the "
                        "chain the writer holds.", cwd=forked)
    rc, out = varve("verify", forked, cwd=forked)
    record("forked", "verify (no expect)", "intact", "intact" if rc == 0 else "broken",
           "the forked chain verifies on its own — that is the point")
    git("add", "-A", cwd=forked)
    git("commit", "-m", "re-chained", cwd=forked)
    git("push", "--force", "origin", "main", cwd=forked)

    rc, status, out = witness(work, ["--ref", "origin/main"])
    record("forked", "witness-check", "DIVERGED", status)

    rc, out = varve("verify", forked, "--expect-head", witnessed, cwd=forked)
    record("forked", "verify --expect-head", "caught", "caught" if rc != 0 else "missed",
           out.splitlines()[-1] if out else "")


def scenario_stale(tmp):
    """The direction e000011 named and did not stage."""
    print("\nC STALE — the same truncation, read through an unrefreshed ref")
    bare, work = build(tmp, "stale", 6)

    # The local checkout's origin/main pointer is current RIGHT NOW. Freeze it
    # there — this is what a container's clone-time fetch leaves behind — and
    # then let the published branch lose its tail.
    frozen = git("rev-parse", "origin/main", cwd=work).strip()

    behind = os.path.join(tmp, "attacker2")
    git("clone", bare, behind, cwd=tmp)
    git("config", "user.email", "probe@example.invalid", cwd=behind)
    git("config", "user.name", "rule5-probe", cwd=behind)
    for name in sorted(os.listdir(os.path.join(behind, "log")))[-2:]:
        os.remove(os.path.join(behind, "log", name))
    git("add", "-A", cwd=behind)
    git("commit", "-m", "truncated", cwd=behind)
    git("push", "--force", "origin", "main", cwd=behind)

    # Restore the fossil pointer: the local ref still names the pre-truncation
    # commit, exactly as it would after a clone that nothing has refetched.
    git("update-ref", "refs/remotes/origin/main", frozen, cwd=work)

    rc, status, out = witness(work, ["--ref", "origin/main", "--no-fetch"])
    # The comparison itself cannot see past a fossil ref — it has nothing but
    # the cached pointer — so the verdict word is still OK. What must not
    # happen is that OK being reported as a discharged rule 5 check. The
    # instrument's answer is its exit status and its UNVERIFIED banner.
    record("stale", "witness-check --no-fetch", "OK", status,
           "the fossil ref cannot see the force-push; the question is what "
           "the tool then claims")
    record("stale", "  ...exit status", "nonzero", "nonzero" if rc != 0 else "zero",
           "an unfetched OK must not exit 0")
    record("stale", "  ...says UNVERIFIED", "yes", "yes" if "UNVERIFIED" in out else "no")

    rc, status, out = witness(work, ["--ref", "origin/main"])
    record("stale", "witness-check (fetches)", "BEHIND", status,
           "the same check, allowed to fetch first")


def scenario_local_stale(tmp):
    print("\nD LOCAL-STALE — published branch is ahead; local checkout is behind")
    bare, work = build(tmp, "ahead", 4)

    pusher = os.path.join(tmp, "pusher")
    git("clone", bare, pusher, cwd=tmp)
    git("config", "user.email", "probe@example.invalid", cwd=pusher)
    git("config", "user.name", "rule5-probe", cwd=pusher)
    for i in range(2):
        varve("append", pusher, "--kind", "hunch",
              "--title", "later entry %d" % (i + 1),
              "--body", "An entry appended and published by another writer, which "
                        "the stale local checkout has never seen.", cwd=pusher)
    git("add", "-A", cwd=pusher)
    git("commit", "-m", "two more entries", cwd=pusher)
    git("push", "origin", "main", cwd=pusher)

    rc, status, out = witness(work, ["--ref", "origin/main"])
    record("local-stale", "witness-check", "AHEAD", status,
           "witness-check documents AHEAD as 'the local checkout is stale, "
           "not the witness'")


def scenario_duplicate_keys(tmp):
    """The published bytes are the ones rule 5 sends a stranger to read.

    e000005 defect 6 established that a duplicate JSON key splits the record
    from the bytes: a human reads the first value, json.load keeps the last.
    store.read_log was taught to refuse such a file. This asks whether the
    tool that inspects the PUBLISHED copy learned the same lesson.
    """
    print("\nE DUPLICATE-KEYS — published entry carries two bodies")
    bare, work = build(tmp, "dupes", 5)

    forger = os.path.join(tmp, "forger")
    git("clone", bare, forger, cwd=tmp)
    git("config", "user.email", "probe@example.invalid", cwd=forger)
    git("config", "user.name", "rule5-probe", cwd=forger)

    target = sorted(os.listdir(os.path.join(forger, "log")))[-1]
    path = os.path.join(forger, "log", target)
    with open(path, encoding="utf-8") as fh:
        raw = fh.read()
    doc = json.loads(raw)
    # Insert a SECOND "body" ahead of the real one. A reader looking at the raw
    # file — which is what a repository browser shows — sees the first value.
    # json.load, and therefore every varve view, keeps the last. seq, id and
    # hash are untouched, so anything comparing only those sees no difference.
    forged = raw.replace(
        '"body":', '"body": "This entry says something else entirely.", "body":', 1)
    if forged == raw or json.loads(forged)["body"] != doc["body"]:
        raise RuntimeError("probe could not construct the duplicate-key file")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(forged)
    git("add", "-A", cwd=forger)
    git("commit", "-m", "duplicate key", cwd=forger)
    git("push", "--force", "origin", "main", cwd=forger)

    rc, out = varve("verify", forger, cwd=forger)
    record("dupe-keys", "verify (on those bytes)", "refuses", "refuses" if rc != 0 else "accepts",
           out.splitlines()[-1] if out else "")

    rc, status, out = witness(work, ["--ref", "origin/main"])
    record("dupe-keys", "witness-check", "not-OK", "OK" if status == "OK" else "not-OK",
           "OK here means the witness certifies bytes varve itself refuses to read")
    record("dupe-keys", "  ...names the file", "yes",
           "yes" if "problem:" in out and target in out else "no")


def main():
    tmp = tempfile.mkdtemp(prefix="rule5-probe-")
    try:
        scenario_truncated(tmp)
        scenario_forked(tmp)
        scenario_stale(tmp)
        scenario_local_stale(tmp)
        scenario_duplicate_keys(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    bad = [r for r in RESULTS if not r[4]]
    print("\n%d checks, %d unexpected" % (len(RESULTS), len(bad)))
    for scenario, instrument, expected, got, _, _ in bad:
        print("  UNEXPECTED  %s / %s: expected %s, got %s"
              % (scenario, instrument, expected, got))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
