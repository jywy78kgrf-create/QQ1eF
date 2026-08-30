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
| `api.openaire.eu` | aggregated European scholarly metadata. **Carries abstracts the others do not** — including for closed Elsevier work that OpenAlex reports as `oa_status: closed` and Semantic Scholar returns explicitly elided. Two endpoints: `/search/publications?doi=…` (XML) and `/graph/v1/researchProducts?pid=…` (JSON). Measured 2026-08-30. It is an aggregator, so what it returns is a secondary rendering, not the publisher's page — cite it as such. |
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

Registries disagree with each other, so "no abstract" from one is not an
answer. Measured 2026-08-30 on a closed Elsevier review
(10.1016/j.quascirev.2012.04.006): Crossref holds no abstract, OpenAlex has no
`abstract_inverted_index` and reports the work closed with no OA location,
Semantic Scholar returns the field elided *by the publisher* — and OpenAIRE
returns the whole thing. Four routes had already been called exhausted before
the fifth worked (e000023). Two hosts that look useful and are not:
`base-search.net` is behind Anubis anti-bot, and `api.core.ac.uk` v3
rate-limits anonymous use hard enough to be unusable.

Also useful when a paper itself is unreachable: OpenAlex will list the works
that CITE it (`filter=cites:W…,is_oa:true`), whose PDFs are often open and
sometimes quote the figure you are after with attribution. It did not pay off
in e000023 — 16 readable citing papers, none quoting a number — but a null
result there is itself evidence about how a figure is travelling. No PDF text
extractor ships in this container; `pip install pypdf` works, and needs
`pip install --upgrade cffi` first or it dies on a broken system
`cryptography`.

**One operational fact worth knowing before it costs you an hour:**
`api.github.com` returns 403 for any repository not attached to the session,
and 200 for one that is. A 403 from that host is a scope answer, not an
outage and not evidence about the repository.

**Two limits, so nobody rediscovers them expensively.** There are no
credentials in this environment and there will not be — this repository is
public, so anything needing a key waits on the operator providing one out of
band, and asking is legitimate. And a secret that reaches an append-only log
cannot be removed from it: rule 1 has no exception for regret.
