# econ.chrislawrence.ca — build plan

The capstone. Ten sites each answer one narrow question; this one asks the only
question none of them can: **what do all ten say at once, and in what order do they
usually speak?**

Nothing here is a new measurement. Every number on this page was computed by one of the
ten trackers and is rendered in that tracker's own words, with that tracker's own
printed rule attached. econ's job is arrangement, not authorship. Where it computes
anything itself it is a normalization of series the trackers already published, done at
render time so the raw series stays the artifact of record.

Site eleven, and the reason `econ-core` exists. Written 2026-09-07; every sibling probed
live that day.

## Why this is now possible

econ-core's CONTRACT.md specifies `analysis.status.headline`: a binary state, a label
that asserts something about the world, the figures behind it, the observation date it
was computed from, and the printed rule. All ten siblings publish it as of 2026-09-07
and mirror it onto `/api/health`. That block is the entire interface. econ reads it and
knows nothing else about the page that produced it.

## Verified inputs (all probed live 2026-09-07)

Every sibling is reachable by container name on the `web` docker network and returns a
contract-valid headline on both `/api/data` and `/api/health`:

| Tracker | Host | Port | State at probe | Lead measure it publishes |
|---|---|---|---|---|
| diesel | `diesel-api` | 8000 | signal | none: scores a percentile, not an episode |
| debt | `debt` | 80 | signal | none: scores a level against a dated record |
| jobs | `jobs` | 80 | normal | none: scores a threshold (Sahm) |
| yield | `yield` | 80 | normal | `median_lead_months` = 12 |
| housing | `housing` | 80 | normal | `median_lead_from_crest_months` = 20 |
| credit | `credit` | 80 | normal | `median_lead_from_trough_months` = 11 |
| lending | `lending` | 80 | normal | `median_lead_from_alarm_months` = 1; contraction lag +8 |
| freight | `freight` | 80 | normal | `median_lead_from_crest_months` = 14.5 |
| consumer | `consumer` | 80 | signal | peak +13.5, slump −1; spending contraction lag +2 |
| output | `output` | 80 | normal | crest 0, alarm −4; two-quarter rule lag +1q |

Note the stat keys differ per tracker because each names its own clock. econ carries a
small hand-declared map from tracker to (which stat is its lead measure, what that clock
is called), with a provenance note per entry. That map is curated content, not
inference: guessing which key means "lead" would eventually pick up the wrong one.

**Three trackers have no lead measure and will not be given one.** diesel scores the
current refining margin's percentile against its own history, debt scores a level
against the 1946 record, and jobs scores the Sahm threshold. None of them date episodes,
so none of them can be ranked in a sequence of leads. They appear on the board with
their state and are explicitly absent from the sequence table, with the reason printed.

## The features: three, and no fourth

**1. The board.** One row per tracker: state dot, label, detail, as-of, and the rule on
hover, rendered verbatim from each headline block. Sorted signal-first, then by as-of.
This is the thing the status-block contract was written to make possible, and it is the
page's spine. A tracker that cannot be reached renders its last known row with its own
`as_of` and a visible staleness marker; it never renders blank and never silently shows
yesterday's state as today's.

**2. The sequence, computed.** The family's thesis as one ranked table: each tracker's
own median lead, in months, ordered longest-lead to longest-lag. On the probe data that
reads housing +20, freight +14.5, consumer's confidence peak +13.5, yield +12, credit's
complacency trough +11, lending's alarm +1, output's crest 0, consumer's slump −1,
output's alarm −4, consumer spending −2, lending volumes −8.

Two things must be got right and stated. **Sign convention**: a lead is positive and a
lag is negative, so the contraction tables (which publish positive lags) are negated to
sit on one axis, and the table says so in its header rather than in a footnote nobody
reads. **These are medians of different episode counts over different eras** on
different definitions of an episode: credit's century of twelve blowouts and lending's
survey era of four are not the same sample, and the table prints the count and the span
beside every row so the ordering cannot be read as more precise than it is.

**3. The overlay.** One headline series per tracker on one axis, z-scored against a
trailing 10-year window, with percentile rank as the alternate view. Exactly the
convention econ-core reserved, computed here from `obs` at render time; no normalized
series is ever stored. Recession bands from the shared dataset.

A caveat that goes on the card, not in a comment: **z-scoring a trending level measures
its deviation from its own recent trend, not its level.** Industrial production and debt
to GDP rise across decades; their z-scores say "unusual for the last ten years", which
is the right question for a cycle dashboard and the wrong one for a level comparison.
The trackers themselves are where levels are read.

## Architecture

Clone the family shell. nginx front `econ` (host port **8137**, verified free) + stdlib
sidecar `econ-updater`. Vendor econ-core for `recessions.json` and the fetch helpers.

The updater fetches the ten siblings' `/api/data` over the `web` network on a schedule,
extracts three things per tracker (the headline block, the declared lead stat, and the
one declared headline series), and writes a compact `board.json`. It does not mirror
whole payloads: the trackers are 200KB to 2MB each and econ needs a few hundred
observations from each, not seventeen thousand.

Guardrails, inherited: a sibling that fails to answer carries its previous row forward
with the error recorded and the staleness shown; a sibling whose headline is missing or
malformed renders as a visible gap rather than being dropped from the board. econ never
writes a value it did not receive.

Host cron daily at 07:40 PT, after every sibling's own refresh window (07:10 through
07:30), so the board reflects the same morning's data. Monthly log truncation.

## Page

1. Header, the question, and a chip that is itself computed: how many of the ten are in
   signal, from the board.
2. The board: ten rows, signal-first.
3. The sequence table with its sign convention in the header, episode counts and spans
   per row, and the three level-scoring trackers listed beneath as explicitly having no
   lead measure.
4. The overlay chart with the z-score / percentile toggle, a tracker multi-select, and
   recession bands.
5. A short "how to read this" card: econ authors nothing, every figure links back to the
   tracker that computed it and to that tracker's printed rule.
6. Sources card: the ten trackers with links, the contract, the fetch policy, provenance.

## Deploy checklist

Port 8137; `sites/econ.caddy`; services.yml entry with dashy + kuma blocks;
`cf-access.sh create econ.chrislawrence.ca --policy public` then poll for the bypass;
cron + truncation; screenshots (mobile fullPage, desktop, board, sequence) + layout audit
+ console check; `ls -l data/`; commit; push private `Lawrence908/econ`.

## Anti-goals

- **No composite index and no house recession probability.** The entire discipline of
  this family is refusing to fabricate a number; a single "econ score" would be exactly
  that, and it would be the most quotable and least defensible thing on the site.
- **No restating a sibling in econ's own words.** Labels, details and rules render
  verbatim. If econ and a tracker ever disagree, the tracker is right and econ has a bug.
- **No fabricated lead for the three trackers that do not date episodes.**
- No forecasting the next turn from the sequence table. It is a description of eleven
  historical orderings with small samples, not a schedule.
- No emdashes in page copy.

## Acceptance

- All ten siblings fetched with zero errors on a cold start; every row contract-valid.
- Killing any one sibling container degrades exactly one row to stale-with-reason and
  leaves the other nine and both computed tables intact.
- The sequence table's ordering matches the ten trackers' own published stats exactly,
  verified by reading each tracker's `/api/data` independently.
- No value on the page is authored by econ: every figure traces to a sibling's payload
  or to a z-score computed from a sibling's `obs`.
- Kill `FRED_API_KEY`: econ never had one and never needs one; it fetches no upstream.
- Both containers healthy, public 200, screenshots committed, zero console errors, no
  horizontal scroll, repo pushed, no machine-owned files in git.
