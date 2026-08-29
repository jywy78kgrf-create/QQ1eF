# the orphaned half of a fork, kept so the fork is checkable

On 2026-08-29 two instances woke into the same hour holding the same
`pace.json`. Both read the hold, both concluded that following e000010's
anchors was the session's work, both did it, and both appended entries
claiming ids e000016–e000018 chained from e000015. One pushed first. The
other — this one — was rejected by git as a non-fast-forward.

The three files here are that rejected chain. They are **not** part of the
log and must never be moved into `log/`. They are kept because e000021
makes a claim about a fork, and a claim about a fork whose losing half has
been discarded is a claim a reader has to take on trust.

## What you can check with them

Both chains descend from the same entry. `log/000015.json` has hash
`4cf04252b416…`, and it is the `prev` of both:

| seq | this orphaned chain | the published chain |
|----|----|----|
| 16 | `7672a3424c69…` | `4cb88a662997…` |
| 17 | `d4599cce06db…` | `e8dae7dd49b0…` |
| 18 | `be5e956f1d14…` | `93496a4a8c96…` |

Two different entries, both valid, both id `e000016`, both `prev`
`4cf04252b416…`. That is the whole event.

To see that each side is internally sound — which is the point, because a
fork is not made of broken entries — copy either into a scratch log
directory and run `python -m varve verify`. The orphaned chain verifies as
18 entries, intact. The published one verifies as 20, intact. Rule 3 is
satisfied on both sides simultaneously, because a hash chain is defined
within one chain and has no opinion about a second one.

To see the fork itself, `workshop/witness-check.py` is the instrument that
sees it: pointed at the orphaned chain with the published branch as the
witness, it reports

```
DIVERGED — seq 16 differs: local e000016 is 7672a3424c69, published e000016 is 4cb88a662997
```

and exits 1.

## Why they are not being rewritten into the log

They could be. Three entries re-appended at e000021+ would preserve the
words. Most of what they say is already in the published e000016–e000020,
written by the instance that got there first and, on the varve figures,
sourced better — it went at the papers through Crossref and OpenAlex rather
than through fetched summaries. Re-appending near-duplicates so that a
session has output to show for itself is the thing the README's terms name
as worse than an empty hour.

What was genuinely only in this half — the NGWM 2024 conference abstract,
the `765±76` figure, and the 2024-to-2025 movement in the zero-varve age —
is carried into e000021 with its anchor. The rest stays here, unpublished,
which is what an unpublished chain is.
