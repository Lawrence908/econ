# The Cycle Board

The capstone of the economic tracker family. Ten narrow trackers, each answering one
question, read together on one page. Live at [econ.chrislawrence.ca](https://econ.chrislawrence.ca).

**This site authors nothing.** Every state and figure on the board was computed by the
tracker it names and is rendered in that tracker's own words with that tracker's own
printed rule attached. What this page adds is arrangement, and one arithmetic the
trackers cannot do alone: putting their clocks in order.

No framework, no build step, no package manager. Plain HTML, CSS and vanilla JS on an
nginx front, with a stdlib-Python aggregator sidecar. Part of the collection on the
shared [`econ-core`](../econ-core/CONTRACT.md) contract.

## Layout

```
src/index.html    markup, styling, the TimeChart canvas engine, every render function
data/board.json   machine-fetched from the ten trackers, rewritten wholesale each run
data/meta.json    curated; deliberately near-empty
data/recessions.json  vendored from econ-core; never edited here
api/server.py     the aggregator, the tracker map, the clock map, read-only status API
api/econcore.py   vendored, stamped copy of the shared helpers
```

## The interface

Each tracker publishes `analysis.status.headline` per econ-core's contract: a binary
state, a label asserting something about the world, the figures behind it, the
observation date it was computed from, and the printed rule. **That block is this page's
entire interface.** It reads nothing else about the page that produced it, which is why
any tracker can be rewritten without touching this one.

This site fetches no upstream data source and holds no API key. It reads the ten
trackers over the internal docker network daily at 07:40 Pacific, after each of them has
refreshed (07:10 through 07:30).

## Three features, and no fourth

**The board.** One row per tracker, signalling ones first, each rendered verbatim with
its rule on hover. A tracker that cannot be reached keeps its last known row, marked
stale and dated to its own last observation, because a stale reading is still a true
reading about its own date; presenting it as today's would not be.

**The sequence.** The family's thesis as one ranked table: each tracker's own median
lead, ordered. On current data, housing's starts crest +20 months, freight's tonnage
crest +14.5, the consumer's confidence peak +13.5, the curve's first inverted month +12,
credit's complacency trough +11, lending's standards alarm +1, **production's crest at
exactly 0**, then the confirming half: the sentiment slump −1, spending contraction −2,
the two-quarter rule −3, production's alarm −4, and loan contraction −8.

Production's crest at zero is the hinge. Industrial production is one of the series the
NBER's committee reads to date a recession, so it does not anticipate the cycle, it
constitutes it. Everything below that line is confirming something already underway.

Two things the table prints rather than footnotes. **Leads are positive and lags
negative**, so the four tables publishing a lag are negated onto one axis with both
figures shown. And **the medians come from samples that are not comparable**: credit's
twelve credited episodes span 1921 to 2022 against a loan-officer survey that only
starts in 1990, on definitions each tracker chose for its own series. Every row carries
its episode count and span.

**Three trackers are deliberately absent from the sequence.** diesel scores a percentile,
debt a level against the 1946 record, jobs the Sahm threshold. None date episodes, so
none can be ranked among leads, and the page says so instead of inventing one.

**The small multiples.** Every tracker's headline series scored against its own trailing
ten years, ten panels on shared axes. Ten panels rather than ten lines on one chart
because ten overlaid series is a colour puzzle rather than a chart. A toggle switches
z-score for percentile rank, and another orients each series so stress reads upward; the
orientation is declared per tracker in the source and printed, never applied silently.

## What is computed here, and where

Exactly two transforms, and neither is a new measurement:

- **the monthly resample**, in the updater: overlay series are reduced to one
  observation per month, keeping the last in each month, because a daily crack spread
  and a quarterly survey cannot otherwise share an axis;
- **the z-score or percentile**, in the browser at render time, from the raw monthly
  observations in the payload. Never stored, because the raw series is the artifact of
  record and a normalized one is a view of it. This is the convention econ-core reserved
  before any of the trackers were built.

A z-score against a trailing ten years is a statement about recent history, not about
levels: industrial production and federal debt both rise across decades, and scoring
them this way asks whether they are unusual for the last ten years. That is the right
question for a cycle board and the wrong one for comparing levels. The trackers are where
levels are read.

## There is no composite score

There will not be one. Ten honest indicators averaged into a single number would be the
most quotable and least defensible thing on the site, and it would hide exactly the
disagreements the board exists to show.

## The updater

```bash
docker exec econ-updater python /app/server.py --once      # dry run
docker exec econ-updater python /app/server.py --refresh   # what cron runs
```

Host crontab, daily at 07:40 Pacific, log bounded monthly. A failed tracker carries its
previous row and its previous clocks forward, both marked, with the error recorded: a
median over decades of episodes does not change because a container was briefly
unreachable.

## Provenance

Assembled with Claude, made by Anthropic. Arrangement and normalization only; no figure
on this page originates here.
