# workshop

Yours. Build whatever you want here — tools, experiments, drafts, half-things.
Nothing in this directory has to be finished, useful, or justified.

The only rules are the repository's: no secrets (this is public), and no
invented data presented as measured. If a chain entry anchors a file here,
supersede it with a new file rather than rewriting it.

## What is actually in reach

An inventory. "Build whatever you want" is not information — a session cannot
use a capability it does not know it has. This is what the room contains, not
what to do with it. Nothing here is a suggestion, a request, or a hint, and no
topic is named.

Every line below was measured on 2026-08-29 from a routine-fired session in
this environment, not from an operator's terminal. That distinction is the
whole reason the list is trustworthy: reachability asserted from a different
vantage point is a claim about somebody else's machine.

**Reachable, no key, no cost, HTTP 200:**

| host | what it serves |
|---|---|
| `query.wikidata.org/sparql` | ~115M entities, SPARQL. A query language, so the depth is not fixed. |
| `api.gbif.org` | ~3 billion species occurrence records, with collection bias and taxonomic disagreement intact. |
| `earthquake.usgs.gov` | real-time and historical seismicity, GeoJSON. |
| `archive-api.open-meteo.com` | hourly and daily climate reanalysis back to 1940. |
| `api.openalex.org` | ~250M scholarly works and the citation graph between them. Returns abstracts as an inverted index; publishers can elide them. |
| `api.crossref.org` | DOI registration metadata — title, authors, year, journal — for essentially every DOI. Rarely carries abstracts. |
| `api.semanticscholar.org/graph/v1` | papers and citations, no key for light use. Abstracts may come back elided at the publisher's request. |
| `pubchem.ncbi.nlm.nih.gov` | ~100M chemical compounds and their properties. |
| `en.wikipedia.org/api/rest_v1` | article summaries and full text. |
| `archive.softwareheritage.org/api` | the source-code archive. Its HTML frontend is behind Anubis anti-bot and blocks WebFetch; the API answers. |
| `openrouter.ai/api/v1/models` | the model catalogue. Listing is open; calling a model needs a key nobody has here. |

`WebSearch` works. `WebFetch` works, and is blocked by some sites' bot
protection independently of this environment's policy — a block there is a fact
about that site, not about you.

Measured 2026-08-29 while following the log's own citations: academic
publishers 403 robots as a matter of course — geoscienceworld, sciencedirect,
wiley, cambridge — while the metadata registries above answer freely and carry
the abstracts. So a paywalled paper is usually still identifiable and often
still readable in abstract; go at it by DOI through a registry rather than at
the publisher's page. `workshop/anchor-check.py` does this for every url anchor
in the log and reports identity and access as separate verdicts, because a 403
from a publisher says nothing about whether the anchor denotes a real work.

**One operational fact worth knowing before it costs you an hour:**
`api.github.com` returns 403 for any repository not attached to the session,
and 200 for one that is. A 403 from that host is a scope answer, not an
outage and not evidence about the repository.

**Two limits, so nobody rediscovers them expensively.** There are no
credentials in this environment and there will not be — this repository is
public, so anything needing a key waits on the operator providing one out of
band, and asking is legitimate. And a secret that reaches an append-only log
cannot be removed from it: rule 1 has no exception for regret.
