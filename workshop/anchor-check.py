#!/usr/bin/env python3
"""anchor-check — resolve the url anchors in a varve log and say what a
stranger following one actually gets.

Rule 2 says a claim about the world carries "an anchor a stranger could
follow to check the claim". The gate checks two of the three anchor kinds
it accepts: `entry` anchors must name an existing entry, and `file` anchors
must name a file that exists under the log root. Both are checkable offline
at write time. `url` anchors are checked for shape and nothing else, because
at write time the network may not be there — and in this log's first days it
was not. So the one anchor kind that points OUTSIDE the repository is the one
kind nothing has ever verified.

This tool does not verify claims. It cannot: no program can tell you whether
a paper says what an entry says it says. It answers the strictly weaker
question that a reader still needs answered first, and that turns out to be
the question that separates the two ways a url anchor fails:

    IDENTITY   does this url denote a real, findable work, and which one?
    ACCESS     can a reader, from here, right now, read it?

These come apart in both directions and the difference matters. A DOI whose
publisher returns 403 to every robot still has perfect identity: Crossref
will name the work, and a human with a library card reads it fine. A url
that returns a cheerful 200 may be a search page, a redirect to a paywall
notice, or a site that has quietly reassigned the address. Reporting either
one as simply "ok" or simply "broken" tells a reader the wrong thing.

So each anchor gets two verdicts, never collapsed into one.

Identity, in order of strength:
  RESOLVED     a DOI (or a landing page carrying one) that Crossref or
               OpenAlex resolves to a titled work. The title is printed, so
               a reader can see whether the anchor denotes what the citing
               entry claims it denotes. This survives the site going down.
  UNREGISTERED a plain url with no DOI behind it. Not a defect — a
               repository, a museum page, a dataset are all legitimate
               anchors — but its identity rests on the host alone.

Access, as observed from wherever you run this:
  READABLE      fetched, with a body.
  BLOCKED       403/429, or a challenge page. A fact about that host's bot
                policy, not about the anchor and not about your network.
  MISSING       404/410. The address no longer denotes anything.
  NO-SUCH-HOST  the hostname does not resolve in DNS.
  UNREACHABLE   timeout, TLS error, proxy refusal, or a blocked egress policy.

NO-SUCH-HOST is separated from UNREACHABLE deliberately, and the separation
was forced by a live case: an anchor added to this log pointed at a host that
does not exist. Through a proxy, that arrived as a 502 tunnel error, which is
indistinguishable at the HTTP layer from the proxy being unwell — so the first
version of this tool reported it as UNREACHABLE and exited 0, which is to say
it reported a permanently dead address as a passing weather condition. A
hostname is resolved explicitly, before the fetch and independent of any
proxy, precisely so that this one case cannot hide inside the transient one.

The distinction is the whole point of the tool, so it is worth stating what
it costs to ignore: an entry in this log (e000010) recorded that every one
of its anchors returned EGRESS_BLOCKED and that it had therefore read none
of them. That was an ACCESS observation, correctly made and honestly
reported. It says nothing either way about whether those anchors identify
the works the entry cites — and they do, which a later session could only
discover by asking the two questions separately.

Usage:
    python3 workshop/anchor-check.py [LOG_ROOT] [--offline] [--json]
                                     [--entry e000010] [--timeout N]

    --offline   inventory the anchors and touch no network. Prints what
                WOULD be checked. Useful for seeing the shape of the log's
                outward surface with egress off.
    --entry     restrict to one entry id (repeatable).
    --json      machine-readable, for a caller that wants to diff two runs.

Exit status is 0 unless an anchor is MISSING or NO-SUCH-HOST, i.e. an
address in an append-only log has stopped denoting anything. BLOCKED and
UNREACHABLE do not fail the run: neither is a property of the log, and a
tool that exits nonzero because somebody's CDN dislikes robots teaches its
reader to ignore it. Rule 1 means a rotted anchor can never be edited out;
the honest response to one is an errata entry, which is why it is worth
exiting nonzero to say so and worth NOT exiting nonzero for anything else.

No dependencies beyond the standard library, no key, no cost.
"""

import json
import os
import re
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request

UA = "varve-anchor-check/1 (+https://github.com/jywy78kgrf-create/QQ1eF)"

# A DOI is 10.<registrant>/<suffix>. The suffix runs to whitespace; trailing
# punctuation is stripped below because DOIs are routinely written into prose
# followed by a comma or a full stop.
DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"'<>]+)", re.I)


def find_doi(url):
    """Return the DOI inside a url, or None.

    Handles doi.org/<doi>, dx.doi.org/<doi>, and publisher landing pages
    that embed the DOI in their path (geoscienceworld and Wiley both do).
    """
    m = DOI_RE.search(urllib.parse.unquote(url))
    if not m:
        return None
    return m.group(1).rstrip(".,;)]}'\"")


def get_json(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def resolve_identity(doi, timeout):
    """Name the work a DOI denotes. Crossref first, OpenAlex as fallback.

    Two registries rather than one because agreeing on the title is itself
    evidence, and because either can be down without the anchor being bad.
    Returns (title, byline, registry) or (None, None, None).
    """
    quoted = urllib.parse.quote(doi, safe="")
    try:
        m = get_json("https://api.crossref.org/works/" + quoted, timeout)["message"]
        title = (m.get("title") or [None])[0]
        if title:
            authors = m.get("author") or []
            names = [a.get("family") or a.get("name") or "" for a in authors[:3]]
            names = [n for n in names if n]
            year = ((m.get("issued") or {}).get("date-parts") or [[None]])[0][0]
            byline = ", ".join(names)
            if len(authors) > 3:
                byline += " et al."
            if year:
                byline = (byline + " " if byline else "") + str(year)
            return title.strip(), byline.strip(), "crossref"
    except Exception:
        pass
    try:
        w = get_json("https://api.openalex.org/works/doi:" + quoted, timeout)
        title = w.get("title")
        if title:
            names = [a["author"]["display_name"] for a in w.get("authorships", [])[:3]]
            byline = ", ".join(names)
            if len(w.get("authorships", [])) > 3:
                byline += " et al."
            year = w.get("publication_year")
            if year:
                byline = (byline + " " if byline else "") + str(year)
            return title.strip(), byline.strip(), "openalex"
    except Exception:
        pass
    return None, None, None


def check_access(url, timeout):
    """Observe what a reader gets from this url, from here, right now.

    Deliberately does not follow cross-host redirects into a verdict of its
    own: a 30x is reported with its destination, because a doi.org anchor
    that redirects to a publisher is behaving correctly and the interesting
    fact is where it lands.
    """
    host = urllib.parse.urlsplit(url).hostname
    if host:
        try:
            # Resolved explicitly rather than left to urlopen, because behind
            # a proxy the connection never does DNS itself: a nonexistent host
            # comes back as a 502 tunnel error, wearing the same clothes as a
            # sick proxy. This is the one check that tells the two apart.
            socket.getaddrinfo(host, None)
        except socket.gaierror as e:
            return "NO-SUCH-HOST", None, "DNS: " + str(e)[:60]
        except Exception:
            pass  # any other resolver trouble is left to the fetch to report

    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(4096)
            code = r.getcode()
            landed = r.geturl()
            note = ""
            if landed != url:
                note = "-> " + urllib.parse.urlsplit(landed).netloc
            if not body.strip():
                note = (note + " " if note else "") + "empty body"
            return "READABLE", code, note
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 429):
            return "BLOCKED", e.code, "host declines robots"
        if e.code in (404, 410):
            return "MISSING", e.code, ""
        return "UNREACHABLE", e.code, e.reason or ""
    except Exception as e:
        return "UNREACHABLE", None, type(e).__name__ + ": " + str(e)[:60]


def load_anchors(root, only):
    """Collect (entry_id, url) pairs in chain order, de-duplicated per url.

    Reads the log directly rather than importing varve, so this stays a
    reader's tool: it must work against a checkout it does not trust and a
    log it cannot append to.
    """
    logdir = os.path.join(root, "log")
    out = []
    seen = {}
    for name in sorted(os.listdir(logdir)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(logdir, name), encoding="utf-8") as f:
            try:
                e = json.load(f)
            except Exception as exc:
                print("  ! %s is not readable JSON: %s" % (name, exc),
                      file=sys.stderr)
                continue
        eid = e.get("id") or name
        if only and eid not in only:
            continue
        anchors = e.get("anchors")
        if not isinstance(anchors, list):
            continue
        for a in anchors:
            if not isinstance(a, dict) or a.get("type") != "url":
                continue
            ref = a.get("ref")
            if not isinstance(ref, str) or not ref.strip():
                continue
            ref = ref.strip()
            if ref in seen:
                seen[ref].append(eid)
                continue
            seen[ref] = [eid]
            out.append((eid, ref))
    return out, seen


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    flags = [a for a in argv[1:] if a.startswith("--")]
    root = args[0] if args else "."
    offline = "--offline" in flags
    as_json = "--json" in flags
    only = set()
    timeout = 20
    for f in flags:
        if f.startswith("--entry="):
            only.add(f.split("=", 1)[1])
        if f.startswith("--timeout="):
            timeout = int(f.split("=", 1)[1])
    # tolerate the spaced form too
    for i, a in enumerate(argv):
        if a == "--entry" and i + 1 < len(argv):
            only.add(argv[i + 1])
        if a == "--timeout" and i + 1 < len(argv):
            timeout = int(argv[i + 1])
    only.discard(root)

    anchors, cited_by = load_anchors(root, only)
    if not anchors:
        print("no url anchors found under %s/log" % root)
        return 0

    rows = []
    for eid, url in anchors:
        doi = find_doi(url)
        row = {
            "url": url,
            "first_cited_by": eid,
            "cited_by": cited_by[url],
            "doi": doi,
            "identity": "RESOLVED" if doi else "UNREGISTERED",
            "title": None, "byline": None, "registry": None,
            "access": None, "status": None, "note": "",
        }
        if not offline:
            if doi:
                t, b, reg = resolve_identity(doi, timeout)
                if t:
                    row.update(title=t, byline=b, registry=reg)
                else:
                    row["identity"] = "UNREGISTERED"
                    row["note"] = "DOI shape, but no registry resolved it"
            acc, code, note = check_access(url, timeout)
            row["access"] = acc
            row["status"] = code
            if note:
                row["note"] = (row["note"] + "; " if row["note"] else "") + note
        rows.append(row)

    if as_json:
        print(json.dumps(rows, indent=1, sort_keys=True))
    else:
        print("anchor-check — %d distinct url anchors in %s/log%s"
              % (len(rows), root, "  [offline: no network touched]" if offline else ""))
        print()
        for r in rows:
            who = ", ".join(r["cited_by"])
            print("%-12s %s" % (who, r["url"]))
            if offline:
                print("             identity: %s%s" %
                      (r["identity"], ("  doi:" + r["doi"]) if r["doi"] else ""))
                continue
            ident = r["identity"]
            if r["title"]:
                ident += "  [%s]" % r["registry"]
            print("             identity: %s" % ident)
            if r["title"]:
                print("               %s" % r["title"])
                if r["byline"]:
                    print("               %s" % r["byline"])
            acc = "%s%s" % (r["access"],
                            (" %s" % r["status"]) if r["status"] else "")
            if r["note"]:
                acc += "   (%s)" % r["note"]
            print("             access:   %s" % acc)
            print()

        if not offline:
            def n(key, val):
                return sum(1 for r in rows if r[key] == val)
            print("identity: %d resolved, %d unregistered"
                  % (n("identity", "RESOLVED"), n("identity", "UNREGISTERED")))
            print("access:   %d readable, %d blocked, %d missing, "
                  "%d no-such-host, %d unreachable"
                  % (n("access", "READABLE"), n("access", "BLOCKED"),
                     n("access", "MISSING"), n("access", "NO-SUCH-HOST"),
                     n("access", "UNREACHABLE")))
            print()
            print("Identity is the durable property; access is a fact about this")
            print("host, this network, and this hour. A BLOCKED anchor with a")
            print("resolved title is a working citation. MISSING and")
            print("NO-SUCH-HOST fail the run; nothing else does.")

    dead = [r for r in rows if r["access"] in ("MISSING", "NO-SUCH-HOST")]
    if dead:
        print("DEAD ANCHORS — rule 1 forbids editing these out; an errata is")
        print("the only honest response:", file=sys.stderr)
        for r in dead:
            print("  %s  %s  (cited by %s)"
                  % (r["access"], r["url"], ", ".join(r["cited_by"])),
                  file=sys.stderr)
    return 1 if dead else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
