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
        if e.get("kind") == "errata" and e.get("corrects"):
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
        if e.get("kind") == "resolution" and e.get("resolves"):
            resolved[e["resolves"]] = (e.get("id", "?"), e.get("outcome"))
    rows = []
    for e in entries:
        if e.get("kind") in ("observation", "hypothesis", "hunch", "prediction"):
            eid = e.get("id")
            if eid in corr:
                status = "corrected by " + ", ".join(corr[eid])
            elif eid in resolved:
                rid, outcome = resolved[eid]
                status = "resolved %s by %s" % (
                    {True: "TRUE", False: "FALSE"}.get(outcome, "?"), rid)
            else:
                status = "standing"
            rows.append((e, status))
    return rows


def unresolved_predictions(entries):
    resolved = {e.get("resolves") for e in entries if e.get("kind") == "resolution"}
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
        pred = by_id.get(r.get("resolves"))
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
