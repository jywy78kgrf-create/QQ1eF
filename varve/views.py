"""Derived views over the log. Views are disposable; the log is the truth.

Nothing here writes anything. A digest or a Brier score you disagree with is
recomputed, never stored — storing a view would create a second, editable
version of the record.
"""

import re
from datetime import datetime, timedelta, timezone

from . import store, validate

# Every string this module prints passes through _flat(). The gate now refuses
# control characters in an authored title or body, but a view is the tool you
# reach for when a log is DAMAGED — including one written before the gate
# refused them, or one whose files a disk-holder edited. So the view defends
# itself rather than trusting that the gate did (third review, 2026-08-24).
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _flat(value):
    """One line, no control characters, safe to print beside an entry id."""
    return _CONTROL.sub(" ", str(value)).strip()


def _parse_ts(ts):
    """The entry's timestamp, or None. Returning None rather than raising is
    the point: '2026-13-45T99:99:99Z' used to pass verify and then take the
    whole digest down with a ValueError from strptime."""
    return validate.parse_ts(ts)


def digest(root, days=7):
    """A 'while you were away' summary of the recent window, as plain text."""
    entries = store.read_log(root)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    undated = [e for e in entries if _parse_ts(e.get("ts")) is None]
    recent = [e for e in entries
              if _parse_ts(e.get("ts")) is not None and _parse_ts(e["ts"]) >= cutoff]
    lines = ["varve digest — last %d day(s), %d entr%s (log ends at %s)" % (
        days, len(recent), "y" if len(recent) == 1 else "ies",
        entries[-1].get("id", "?") if entries else "(empty)")]
    if undated:
        lines.append("  ⚠ %d entr%s with an unreadable timestamp, omitted from the window: %s"
                     % (len(undated), "y" if len(undated) == 1 else "ies",
                        ", ".join(_flat(e.get("id", "?")) for e in undated)))
    for e in recent:
        lines.append("")
        lines.append("%s %s [%s] %s" % (_flat(e.get("id", "?")), _flat(e.get("ts", ""))[:10],
                                        _flat(e.get("kind", "?")), _flat(e.get("title", ""))))
        body = _flat(e.get("body", ""))
        lines.append("  " + (body[:200] + "…" if len(body) > 200 else body))
        anchors = e.get("anchors")
        if isinstance(anchors, list) and anchors:
            lines.append("  anchors: " + "; ".join(
                "%s:%s" % (_flat(a.get("type")), _flat(a.get("ref"))) if isinstance(a, dict)
                else _flat(a) for a in anchors))
    open_preds = unresolved_predictions(entries)
    if open_preds:
        lines.append("")
        lines.append("Open predictions:")
        for e in open_preds:
            p = e.get("prediction")
            p = p if isinstance(p, dict) else {}
            conf = p.get("p")
            lines.append("  %s p=%s resolve by %s — %s" % (
                _flat(e.get("id", "?")),
                ("%.2f" % conf) if isinstance(conf, (int, float)) else "?",
                _flat(p.get("resolve_by", "?")), _flat(p.get("statement", "?"))))
    return "\n".join(lines)


def corrections(entries):
    """Map of entry id -> list of errata entry ids that correct it.

    Append-only means a falsified observation keeps its confident wording
    forever; the correction lives in a later entry. This map is how every
    view keeps an amnesiac reader from acting on a dead claim — the record
    stays intact, the *reading* carries the warning."""
    out = {}
    for e in entries:
        # isinstance, not truthiness. `out.setdefault(e["corrects"], ...)`
        # HASHES the field, so an errata whose 'corrects' is a list or a dict
        # raised TypeError here — on log content `varve verify` calls intact,
        # and out of the one function every other view depends on. The gate
        # now refuses those, but a view is what you reach for when a log is
        # damaged, including one written before the gate refused them
        # (fifth review, 2026-08-30).
        if e.get("kind") == "errata" and isinstance(e.get("corrects"), str) and e["corrects"]:
            out.setdefault(e["corrects"], []).append(e.get("id", "?"))
    return out


def beliefs(root):
    """Current belief state: every claim-bearing entry with its standing.
    Returns rows of (entry, status) where status is 'standing' or
    'corrected by eNNNNNN[, ...]'. Derived, like everything here."""
    entries = store.read_log(root)
    corr = corrections(entries)
    # A resolved prediction is not "standing" — it has been graded, and an
    # amnesiac reader takes "standing" to mean still open. The view was
    # correction-aware but not resolution-aware, so the first forecast this
    # log resolved went on reporting itself as open (third review,
    # 2026-08-24).
    resolved = {}
    for e in entries:
        # Same hashing hazard as corrections() above: this is a dict key.
        if e.get("kind") == "resolution" and isinstance(e.get("resolves"), str) and e["resolves"]:
            resolved[e["resolves"]] = (e.get("id", "?"), e.get("outcome"))
    rows = []
    for e in entries:
        if e.get("kind") in ("observation", "hypothesis", "hunch", "prediction"):
            eid = e.get("id")
            # Both, when both apply. These were an if/elif, so a forecast that
            # had been corrected AND graded reported only the correction — and
            # a reader who is told nothing about the grade concludes the
            # forecast is still open, which is e000009's finding exactly:
            # 'standing' reads as 'still open' to the amnesiac reader rule 6
            # is written for, and silence reads the same way. The correction
            # comes first because it is the do-not-act-on-this warning
            # (fifth review, 2026-08-30).
            parts = []
            if eid in corr:
                parts.append("corrected by " + ", ".join(corr[eid]))
            if eid in resolved:
                rid, outcome = resolved[eid]
                parts.append("resolved %s by %s" % (
                    {True: "TRUE", False: "FALSE"}.get(outcome, "?"), rid))
            status = "; ".join(parts) if parts else "standing"
            rows.append((e, status))
    return rows


def beliefs_lines(root):
    """beliefs(), rendered — one flattened line per claim-bearing entry.

    beliefs() returns structured rows, so until now the CLI formatted them
    itself with e["title"] and no _flat(). That made the CLI a SECOND renderer
    of this module's data, and it inherited neither lesson this module has
    learned: a title-less entry that verify calls intact raised KeyError out
    of `varve beliefs`, and a title carrying newlines printed as extra lines
    that read exactly like further log entries — the digest forgery of
    e000005 defect 7, one function away from where it was fixed. Rendering
    belongs here, beside _flat, where the module comment above is true
    (fourth review, 2026-08-27; workshop/reader-probe.py).
    """
    return ["%s [%s] %s — %s" % (_flat(e.get("id", "?")), _flat(e.get("kind", "?")),
                                 _flat(e.get("title", "")), _flat(status))
            for e, status in beliefs(root)]


def brier_lines(root):
    """brier(), rendered. Same reasoning as beliefs_lines: a forecast's
    statement is author-supplied text printed beside an entry id."""
    score, n, rows = brier(root)
    if not n:
        return ["no resolved predictions yet"]
    lines = []
    for pred, res, s in rows:
        p = (pred.get("prediction") or {}) if isinstance(pred.get("prediction"), dict) else {}
        lines.append("%s p=%s -> %s  (%.3f)  %s" % (
            _flat(pred.get("id", "?")), _flat(p.get("p", "?")),
            "true" if res.get("outcome") else "false", s,
            _flat(p.get("statement", "?"))))
    lines.append("brier %.3f over %d forecast(s)  [0=prophet, 0.25=coin at p=.5]" % (score, n))
    return lines


def unresolved_predictions(entries):
    # A SET of author-supplied values: an unhashable 'resolves' on disk took
    # down digest and brier as well as this function. An unreadable pointer
    # resolves nothing, so it is dropped rather than matched — which leaves
    # the prediction reported as still open, the safe direction to be wrong
    # in (fifth review, 2026-08-30).
    resolved = {e.get("resolves") for e in entries
                if e.get("kind") == "resolution" and isinstance(e.get("resolves"), str)}
    return [e for e in entries
            if e.get("kind") == "prediction" and e.get("id") not in resolved]


def brier(root):
    """Calibration over resolved predictions.

    Brier score = mean (p - outcome)^2; 0 is prophecy, 0.25 is coin-flipping
    at p=0.5, 1 is confident wrongness. Returns (score, n, rows) where rows
    are (prediction entry, resolution entry, per-forecast score).
    """
    entries = store.read_log(root)
    by_id = {e.get("id"): e for e in entries}
    rows = []
    for r in (e for e in entries if e.get("kind") == "resolution"):
        # dict.get hashes its argument, so an unhashable 'resolves' crashed
        # the calibration report here too. A resolution that points at nothing
        # readable scores nothing, like the damaged predictions below.
        ref = r.get("resolves")
        if not isinstance(ref, str):
            continue
        pred = by_id.get(ref)
        if pred is None:
            continue
        # A damaged prediction scores nothing rather than taking the whole
        # calibration report down with it.
        p = (pred.get("prediction") or {}).get("p") if isinstance(pred.get("prediction"), dict) else None
        if not isinstance(p, (int, float)) or not isinstance(r.get("outcome"), bool):
            continue
        outcome = 1.0 if r["outcome"] else 0.0
        rows.append((pred, r, (p - outcome) ** 2))
    if not rows:
        return None, 0, []
    score = sum(s for _, _, s in rows) / len(rows)
    return score, len(rows), rows
