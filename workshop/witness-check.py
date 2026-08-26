#!/usr/bin/env python3
"""witness-check — is the log a stranger can read the same log the writer holds?

Rules 1-4 are about the bytes on the writer's disk, and `varve verify` checks
exactly those. Rule 5 is about the bytes anyone else can reach, and nothing in
varve/ looks at those at all. This script does.

It compares the local chain against the chain published on a git ref — by
default the remote's default branch, which is what a stranger lands on — and
distinguishes the two ways they can differ:

  BEHIND    the published chain is a proper prefix of the local one.
            Nothing is wrong with either log; the witness is just stale, so
            the published head cannot corroborate anything written since.
  DIVERGED  some sequence number carries a different hash on each side.
            One of them is not the log the other one is.

The distinction matters because only the second is an integrity failure, and
because the first is the one that happens by accident. It happened here: on
2026-08-26 the default branch held entry 1 of 9 (see e000011).

    python3 workshop/witness-check.py .                 # vs origin's default branch
    python3 workshop/witness-check.py . --ref origin/main
    python3 workshop/witness-check.py . --no-fetch      # use the cached ref

Exit status is 0 only when the published chain and the local chain have the
same head. BEHIND and DIVERGED both exit 1, because a witness that is not
current is not a witness.
"""

import argparse
import json
import os
import subprocess
import sys


def git(*args, cwd=None):
    """Run git, returning stdout. Raises CalledProcessError on failure."""
    out = subprocess.run(
        ("git",) + args, cwd=cwd, check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return out.stdout.decode("utf-8", "replace")


def default_ref(repo):
    """The ref a stranger sees: origin's HEAD, falling back to origin/main."""
    try:
        return git("symbolic-ref", "--short", "refs/remotes/origin/HEAD", cwd=repo).strip()
    except subprocess.CalledProcessError:
        pass
    # origin/HEAD is often unset in a fresh clone. Ask the remote directly.
    try:
        for line in git("remote", "show", "origin", cwd=repo).splitlines():
            if "HEAD branch:" in line:
                return "origin/" + line.split(":", 1)[1].strip()
    except subprocess.CalledProcessError:
        pass
    return "origin/main"


def published_chain(repo, ref, logdir="log"):
    """[(seq, id, hash)] for every entry file present under `ref`, seq-ordered.

    Reads blobs out of the git object store rather than the worktree, so it
    reports what the ref actually carries and not what happens to be checked
    out. A file that does not parse, or that carries no hash, is reported as a
    problem rather than skipped: a published log that cannot be read is a rule 5
    failure too, just a louder one.
    """
    problems = []
    try:
        listing = git("ls-tree", "-r", "--name-only", ref, "--", logdir, cwd=repo)
    except subprocess.CalledProcessError as exc:
        raise SystemExit("cannot read %s: %s" % (ref, exc.stderr.decode("utf-8", "replace").strip()))

    entries = []
    for path in sorted(listing.split()):
        if not path.endswith(".json"):
            continue
        raw = git("cat-file", "blob", "%s:%s" % (ref, path), cwd=repo)
        try:
            e = json.loads(raw)
        except ValueError as exc:
            problems.append("%s does not parse under %s (%s)" % (path, ref, exc))
            continue
        if not isinstance(e, dict):
            problems.append("%s under %s is not a JSON object" % (path, ref))
            continue
        seq, h, eid = e.get("seq"), e.get("hash"), e.get("id")
        if not isinstance(seq, int) or not isinstance(h, str):
            problems.append("%s under %s has no usable seq/hash" % (path, ref))
            continue
        entries.append((seq, eid, h))
    entries.sort()
    return entries, problems


def local_chain(root):
    """[(seq, id, hash)] from the working log directory, seq-ordered."""
    entries = []
    logdir = os.path.join(root, "log")
    for name in sorted(os.listdir(logdir)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(logdir, name), encoding="utf-8") as fh:
            e = json.load(fh)
        entries.append((e.get("seq"), e.get("id"), e.get("hash")))
    entries.sort(key=lambda t: (t[0] is None, t[0]))
    return entries


def compare(local, remote):
    """('OK'|'BEHIND'|'AHEAD'|'DIVERGED', detail)."""
    by_seq = {seq: (eid, h) for seq, eid, h in local}
    for seq, eid, h in remote:
        if seq not in by_seq:
            return "DIVERGED", ("published entry %s (seq %s) has no local counterpart"
                                % (eid, seq))
        if by_seq[seq][1] != h:
            return "DIVERGED", (
                "seq %s differs: local %s is %s, published %s is %s"
                % (seq, by_seq[seq][0], _short(by_seq[seq][1]), eid, _short(h)))
    if len(remote) == len(local):
        return "OK", "published head matches local head"
    if len(remote) < len(local):
        missing = [eid for seq, eid, _ in local[len(remote):]]
        return "BEHIND", ("published chain is a prefix: %d of %d entries. "
                          "Unwitnessed: %s" % (len(remote), len(local), ", ".join(missing)))
    return "AHEAD", ("published chain has %d entries, local has %d — the local "
                     "checkout is stale, not the witness" % (len(remote), len(local)))


def _short(h):
    return (h or "")[:12] or "<none>"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root", nargs="?", default=".", help="log directory (default: .)")
    ap.add_argument("--ref", help="git ref to treat as published (default: origin's HEAD branch)")
    ap.add_argument("--no-fetch", action="store_true", help="do not fetch; use the cached ref")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.root)
    ref = args.ref or default_ref(root)

    if not args.no_fetch:
        branch = ref.split("/", 1)[1] if ref.startswith("origin/") else None
        try:
            git("fetch", "origin", *( [branch] if branch else [] ), cwd=root)
        except subprocess.CalledProcessError as exc:
            print("warning: fetch failed, using cached ref (%s)"
                  % exc.stderr.decode("utf-8", "replace").strip().splitlines()[-1:],
                  file=sys.stderr)

    local = local_chain(root)
    remote, problems = published_chain(root, ref)

    print("local     %s  (%d entries)"
          % (_fmt_head(local), len(local)))
    print("published %s  (%d entries)  [%s]"
          % (_fmt_head(remote), len(remote), ref))

    for p in problems:
        print("  problem:", p)

    status, detail = compare(local, remote)
    print("\n%s — %s" % (status, detail))

    if status == "OK" and not problems:
        print("\nA stranger following rule 5 to %s reads the same chain you hold." % ref)
        return 0
    if status == "BEHIND":
        print("\nNothing is corrupt. The published log simply stops earlier than "
              "yours, so nothing after it is witnessed by anyone but you.")
    return 1


def _fmt_head(entries):
    if not entries:
        return "<empty>"
    seq, eid, h = entries[-1]
    return "%s %s" % (eid or "e%06d" % (seq or 0), _short(h))


if __name__ == "__main__":
    sys.exit(main())
