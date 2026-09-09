#!/usr/bin/env python3
"""econ.chrislawrence.ca aggregator and read-only status API.

The capstone. Ten sites each answer one narrow question; this one asks the
only question none of them can: what do all ten say at once, and in what
order do they usually speak?

**econ authors nothing.** Every figure it publishes was computed by one of
the ten trackers and is carried here verbatim, with that tracker's own
printed rule attached. Where this file transforms anything it is one of two
stated operations, and never a new measurement:

  * resampling an overlay series to monthly (last observation in each month),
    because a daily crack spread and a quarterly survey cannot share an axis
    otherwise. Stated on the page;
  * nothing else. Normalization (z-scores against a trailing 10-year window,
    percentile rank as the alternate view) happens in the browser at render
    time, from the raw monthly observations shipped in this payload, exactly
    as econ-core's CONTRACT.md reserved. No normalized series is ever stored,
    because the raw series is the artifact of record.

The interface to every sibling is `analysis.status.headline`, the status
block econ-core specifies: a binary state, a label asserting something about
the world, the figures behind it, the observation date it was computed from,
and the printed rule. econ reads that block and knows nothing else about the
page that produced it.

Two things this file knows so nobody rediscovers them:

  * **diesel has no `series` dict.** It predates the contract's series shape
    and publishes raw parallel columns (`dates`, `us`, `eu`); its overlay
    series is assembled from those. Every other tracker exposes `series`.
  * **the lead statistics are named differently by every tracker**, because
    each names its own clock (crest, trough, alarm, slump, confidence peak).
    The map from tracker to clock is hand-declared below with a note per
    entry. Guessing which key means "lead" would eventually pick the wrong
    one, and a wrong lead here would be laundered through ten sites'
    credibility.

HTTP here is read-only. Runs happen via host cron calling
`docker exec econ-updater python /app/server.py --refresh`.
"""

import json
import os
import sys
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import econcore

DATA_DIR = os.environ.get("DATA_DIR", "/app/data")
BOARD_FILE = os.path.join(DATA_DIR, "board.json")
STATE_FILE = os.path.join(DATA_DIR, "updater-state.json")
RECESSIONS_FILE = os.path.join(DATA_DIR, "recessions.json")

CURATED = ["meta", "recessions"]
FETCH_TIMEOUT = 30

# The warm build races its siblings on a host restart: they are named on the
# same docker network, so an unready sibling is a DNS failure, not a data
# failure. Retry the whole build on a backoff rather than let the boot race
# write a board of carried-forward stale rows that stands until tomorrow's cron.
WARM_ATTEMPTS = 6
WARM_BACKOFF = [15, 30, 60, 120, 240]

# How far back the overlay carries observations. Ten years earlier than the
# chart's own start, because a trailing 10-year z-score needs a decade of
# history before the first point it can score.
OVERLAY_FROM = "1950-01-01"

_payload_cache = {"stamp": None, "body": None}
_state = {"last_run": None, "results": []}
_lock = threading.Lock()


# --------------------------------------------------------------------------
# the trackers
#
# Hand-declared, one entry per sibling. `host` is the container name on the
# `web` docker network. `series` is the one series that tracker's own headline
# question runs on, and `stress` says which direction of that series is the
# stressed one (+1 higher is worse, -1 lower is worse) so the overlay can
# optionally orient them together; the orientation is declared here and
# printed on the page, never applied silently.
# --------------------------------------------------------------------------

TRACKERS = [
    {
        "id": "yield", "host": "yield", "port": 80,
        "name": "The Inverted Yield Curve",
        "question": "Is the curve inverted, and what followed when it was?",
        "url": "https://yield.chrislawrence.ca",
        "series": "us_spread_10y3m_monthly",
        "series_label": "10y minus 3m spread",
        "units": "percentage points", "stress": -1,
    },
    {
        "id": "housing", "host": "housing", "port": 80,
        "name": "Has Housing Rolled Over?",
        "question": "Has housing rolled over, and how early does it turn?",
        "url": "https://housing.chrislawrence.ca",
        "series": "us_starts_1f",
        "series_label": "Single-family housing starts",
        "units": "thousands SAAR", "stress": -1,
    },
    {
        "id": "credit", "host": "credit", "port": 80,
        "name": "Are Credit Spreads Blowing Out?",
        "question": "Are spreads blowing out, and when they did, what followed?",
        "url": "https://credit.chrislawrence.ca",
        "series": "us_quality_spread",
        "series_label": "Baa minus Aaa quality spread",
        "units": "percentage points", "stress": 1,
    },
    {
        "id": "lending", "host": "lending", "port": 80,
        "name": "Are Banks Tightening?",
        "question": "Are banks tightening, and what has followed when they did?",
        "url": "https://lending.chrislawrence.ca",
        "series": "us_std_ci_large",
        "series_label": "C&I lending standards, net tightening",
        "units": "net percent", "stress": 1,
    },
    {
        "id": "freight", "host": "freight", "port": 80,
        "name": "Is Freight Moving?",
        "question": "Is freight moving, and does it warn?",
        "url": "https://freight.chrislawrence.ca",
        "series": "us_truck_tonnage",
        "series_label": "Truck tonnage index",
        "units": "index", "stress": -1,
    },
    {
        "id": "consumer", "host": "consumer", "port": 80,
        "name": "Is the Consumer Holding Up?",
        "question": "Does what consumers say match what they do?",
        "url": "https://consumer.chrislawrence.ca",
        "series": "us_sentiment",
        "series_label": "Michigan consumer sentiment",
        "units": "index", "stress": -1,
    },
    {
        "id": "output", "host": "output", "port": 80,
        "name": "Is the Economy Producing?",
        "question": "Is the economy producing, and does output warn or confirm?",
        "url": "https://output.chrislawrence.ca",
        "series": "us_ip",
        "series_label": "Industrial production",
        "units": "index", "stress": -1,
    },
    {
        "id": "jobs", "host": "jobs", "port": 80,
        "name": "A Century of Work",
        "question": "What has unemployment actually done, over a century?",
        "url": "https://jobs.chrislawrence.ca",
        "series": "us_unemployment_rate",
        "series_label": "US unemployment rate",
        "units": "percent", "stress": 1,
    },
    {
        "id": "debt", "host": "debt", "port": 80,
        "name": "Debt Atlas",
        "question": "How much does everyone owe, against what record?",
        "url": "https://debt.chrislawrence.ca",
        "series": "us_debt_to_gdp_total",
        "series_label": "Gross federal debt to GDP",
        "units": "percent of GDP", "stress": 1,
    },
    {
        "id": "diesel", "host": "diesel-api", "port": 8000,
        "name": "Diesel Crack Spread",
        "question": "What is it worth to turn a barrel into diesel?",
        "url": "https://diesel.chrislawrence.ca",
        # diesel predates the series contract and publishes parallel columns.
        "series": None, "columns": ("dates", "us"),
        "series_label": "US diesel crack spread",
        "units": "USD per barrel", "stress": 1,
    },
]

TRACKERS_BY_ID = {t["id"]: t for t in TRACKERS}


# --------------------------------------------------------------------------
# the clocks
#
# One row per CLOCK, not per tracker: consumer publishes three (a confidence
# peak, a slump, and a spending contraction) and output three. Each entry says
# where the median lives in that tracker's analysis block, what the clock is
# called, and whether the published figure is a LEAD (positive means it
# arrived before the recession) or a LAG (positive means it arrived after, so
# it is negated onto the shared axis).
#
# `kind` is the sign convention, `scale` converts to months. Both travel to
# the page so the table can print them instead of hiding them in a footnote.
# --------------------------------------------------------------------------

LEAD, LAG = "lead", "lag"

CLOCKS = [
    {"tracker": "housing", "clock": "Starts crest", "kind": LEAD, "scale": 1,
     "path": ("episodes", "stats", "median_lead_from_crest_months"),
     "episodes": ("episodes", "episodes"),
     "note": "Housing's early clock: where starts peaked before the alarm."},
    {"tracker": "freight", "clock": "Tonnage crest", "kind": LEAD, "scale": 1,
     "path": ("episodes", "stats", "median_lead_from_crest_months"),
     "episodes": ("episodes", "episodes"),
     "note": "Where truck tonnage peaked before the freight recession began."},
    {"tracker": "consumer", "clock": "Confidence peak", "kind": LEAD, "scale": 1,
     "path": ("slumps", "stats", "median_lead_from_peak_months"),
     "episodes": ("slumps", "episodes"),
     "note": "Peak optimism before the mood broke."},
    {"tracker": "yield", "clock": "First inverted month", "kind": LEAD, "scale": 1,
     "path": ("episodes", "stats", "median_lead_months"),
     "episodes": ("episodes", "episodes"),
     "note": "The month the 10y first fell below the 3m."},
    {"tracker": "credit", "clock": "Complacency trough", "kind": LEAD, "scale": 1,
     "path": ("episodes", "stats", "median_lead_from_trough_months"),
     "episodes": ("episodes", "episodes"),
     "note": "The tightest spread before the blowout: credit's early clock."},
    {"tracker": "lending", "clock": "Standards alarm", "kind": LEAD, "scale": 1,
     "path": ("episodes", "stats", "median_lead_from_alarm_months"),
     "episodes": ("episodes", "episodes"),
     "note": "The first quarter banks tightened past the threshold."},
    {"tracker": "output", "clock": "Production crest", "kind": LEAD, "scale": 1,
     "path": ("downturns", "stats", "median_lead_from_crest_months"),
     "episodes": ("downturns", "episodes"),
     "note": "Where industrial production peaked before the downturn."},
    {"tracker": "consumer", "clock": "Sentiment slump", "kind": LEAD, "scale": 1,
     "path": ("slumps", "stats", "median_lead_from_slump_months"),
     "episodes": ("slumps", "episodes"),
     "note": "The mood breaking, as opposed to peaking."},
    {"tracker": "output", "clock": "Production alarm", "kind": LEAD, "scale": 1,
     "path": ("downturns", "stats", "median_lead_from_alarm_months"),
     "episodes": ("downturns", "episodes"),
     "note": "Production far enough below its crest to clear the threshold."},
    {"tracker": "consumer", "clock": "Spending contraction", "kind": LAG, "scale": 1,
     "path": ("contractions", "stats", "median_lag_months"),
     "episodes": ("contractions", "contractions"),
     "note": "Real consumption actually falling year over year."},
    {"tracker": "output", "clock": "Two-quarter rule", "kind": LAG, "scale": 3,
     "path": ("two_quarter", "stats", "median_lag_quarters"),
     "episodes": ("two_quarter", "firings"),
     "note": "The folk definition, published in quarters and converted at three months each."},
    {"tracker": "lending", "clock": "Loan contraction", "kind": LAG, "scale": 1,
     "path": ("contractions", "stats", "median_lag_months"),
     "episodes": ("contractions", "contractions"),
     "note": "Bank C&I books actually shrinking year over year."},
]

# Trackers that deliberately have no clock, and the reason, printed on the
# page beneath the sequence table. None of them date episodes, so none can be
# ranked among leads; inventing a figure for them would be the easiest lie on
# the site.
NO_CLOCK = {
    "diesel": "Scores the current refining margin's percentile against its own history. It dates no episodes, so it has no lead to measure.",
    "debt": "Scores a level against a dated historical record (the 1946 wartime peak). It dates no episodes.",
    "jobs": "Scores the Sahm threshold, which is a real-time trigger rather than an episode chronology.",
}


# --------------------------------------------------------------------------
# fetching the siblings
# --------------------------------------------------------------------------

def fetch_tracker(spec):
    url = "http://%s:%d/api/data" % (spec["host"], spec["port"])
    req = urllib.request.Request(url, headers={
        "User-Agent": "chrislawrence.ca econ overlay (internal)"})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _dig(doc, path):
    """Walk a tuple path, returning None rather than raising on any miss."""
    node = doc
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def _monthly(obs):
    """Resample to one observation per month, keeping the last in each month.

    A daily crack spread and a quarterly survey cannot share an axis
    otherwise. This is a resample, not a normalization: no value is averaged,
    smoothed or rescaled, and the page says the transform is here.
    """
    out = {}
    for date, value in obs:
        if date < OVERLAY_FROM:
            continue
        out[date[:7]] = value
    return [[m + "-01", v] for m, v in sorted(out.items())]


def extract_series(spec, doc):
    """The one series this tracker's headline question runs on, monthly."""
    if spec.get("series"):
        entry = (doc.get("series") or {}).get(spec["series"])
        if not entry or not entry.get("obs"):
            return None, None
        return _monthly(entry["obs"]), entry.get("source_url")
    # diesel: parallel columns, not the contract series shape.
    date_key, value_key = spec["columns"]
    dates, values = doc.get(date_key) or [], doc.get(value_key) or []
    pairs = [[d, v] for d, v in zip(dates, values) if v is not None]
    return (_monthly(pairs) if pairs else None), spec["url"]


def extract_clocks(payloads):
    """The sequence table: one row per clock, from each tracker's own stats.

    Nothing is recomputed here. The median is the tracker's published median;
    the count and span are read off its published episode list so the table
    can show that a century of twelve blowouts and a survey era of four are
    not the same sample.
    """
    rows = []
    for entry in CLOCKS:
        doc = payloads.get(entry["tracker"])
        if not doc:
            continue
        analysis = doc.get("analysis") or {}
        value = _dig(analysis, entry["path"])
        if value is None:
            continue
        episodes = _dig(analysis, entry["episodes"]) or []
        credited = [e for e in episodes
                    if e.get("recessions") or e.get("recession_peak")]
        starts = [e.get("start") or e.get("start_label") or "" for e in episodes]
        starts = [s[:7] for s in starts if s]
        months = value * entry["scale"]
        rows.append({
            "tracker": entry["tracker"],
            "tracker_name": TRACKERS_BY_ID[entry["tracker"]]["name"],
            "url": TRACKERS_BY_ID[entry["tracker"]]["url"],
            "clock": entry["clock"],
            "note": entry["note"],
            "kind": entry["kind"],
            "published": value,
            "scale": entry["scale"],
            # One axis: a lead is positive, a lag is negative. The published
            # figure is carried alongside so the conversion is auditable.
            "months": months if entry["kind"] == LEAD else -months,
            "episodes": len(episodes),
            "credited": len(credited),
            "span": [starts[0], starts[-1]] if starts else None,
        })
    rows.sort(key=lambda r: r["months"], reverse=True)
    return rows


def build_board(dry=False):
    payloads, board, errors, results = {}, [], {}, []
    previous, previous_clocks = {}, {}
    try:
        with open(BOARD_FILE) as fh:
            stored = json.load(fh)
        previous = {row["id"]: row for row in stored.get("board", [])}
        for clock in stored.get("clocks", []):
            previous_clocks.setdefault(clock["tracker"], []).append(clock)
    except Exception:  # noqa: BLE001 - first run, or corrupt file: start clean
        pass

    for spec in TRACKERS:
        tid = spec["id"]
        rec = {"tracker": tid, "action": "fetched"}
        row = {"id": tid, "name": spec["name"], "question": spec["question"],
               "url": spec["url"], "series_label": spec["series_label"],
               "units": spec["units"], "stress": spec["stress"]}
        try:
            doc = fetch_tracker(spec)
            payloads[tid] = doc
            head = _dig(doc, ("analysis", "status", "headline"))
            if not head:
                raise ValueError("no analysis.status.headline in payload")
            missing = [k for k in ("state", "label", "detail", "as_of", "rule")
                       if not head.get(k)]
            if missing:
                raise ValueError("headline missing %s" % ", ".join(missing))
            obs, source_url = extract_series(spec, doc)
            row.update({
                "headline": head,
                "obs": obs or [],
                "source_url": source_url,
                "series_fetched_at": doc.get("series_fetched_at"),
                "stale": False,
            })
            if not obs:
                rec["note"] = "headline ok, overlay series absent"
        except Exception as exc:  # noqa: BLE001 - one dead sibling, one stale row
            errors[tid] = "%s: %s" % (type(exc).__name__, exc)
            rec.update(action="error", reason=errors[tid])
            prior = previous.get(tid)
            if prior and prior.get("headline"):
                # Carry the last known row forward and mark it. A stale
                # reading is still a true reading about its own date; what
                # would be false is presenting it as today's.
                row = dict(prior)
                row["stale"] = True
                row["stale_reason"] = errors[tid]
                rec["carried_forward"] = True
            else:
                row.update({"headline": None, "obs": [], "stale": True,
                            "stale_reason": errors[tid]})
        board.append(row)
        results.append(rec)
        print("%-10s %-10s %s" % (tid, rec["action"], rec.get("reason", "")),
              flush=True)

    clocks = extract_clocks(payloads)
    # A clock is a median over decades of episodes; it does not change because
    # a container was briefly unreachable. Carry a failed tracker's stored
    # clocks forward, marked, rather than dropping rows out of the sequence.
    fetched = set(payloads)
    for tid, stored_rows in previous_clocks.items():
        if tid in fetched:
            continue
        for row in stored_rows:
            row = dict(row)
            row["stale"] = True
            clocks.append(row)
    clocks.sort(key=lambda r: r["months"], reverse=True)

    live = [r for r in board if r.get("headline") and not r.get("stale")]
    signals = [r for r in live if r["headline"]["state"] == "signal"]

    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "note": "Machine-fetched from the ten trackers. econ authors no figure of its own; every value here was computed by the tracker it is attributed to.",
        "econcore": econcore.VERSION,
        "errors": errors,
        "board": board,
        "clocks": clocks,
        "no_clock": NO_CLOCK,
        "summary": {
            "trackers": len(board),
            "live": len(live),
            "stale": len([r for r in board if r.get("stale")]),
            "signals": len(signals),
            "signal_ids": [r["id"] for r in signals],
        },
    }

    if dry:
        print("dry run: %d trackers, %d clocks, %d errors -- not written"
              % (len(board), len(clocks), len(errors)), flush=True)
        return payload

    tmp = BOARD_FILE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(payload, fh, separators=(",", ":"))
    os.chmod(tmp, 0o644)
    os.replace(tmp, BOARD_FILE)

    with _lock:
        _state["last_run"] = datetime.now(timezone.utc).isoformat()
        _state["results"] = results
    _save_state()

    print("board refreshed: %d trackers (%d live, %d signalling), %d clocks, %d errors"
          % (len(board), len(live), len(signals), len(clocks), len(errors)),
          flush=True)
    return payload


def _save_state():
    try:
        with _lock:
            snapshot = dict(_state)
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(snapshot, fh, indent=2)
        os.chmod(tmp, 0o644)
        os.replace(tmp, STATE_FILE)
    except OSError:
        pass


# --------------------------------------------------------------------------
# read-only HTTP
# --------------------------------------------------------------------------

def _load(name):
    with open(os.path.join(DATA_DIR, name)) as fh:
        return json.load(fh)


def data_stamp():
    newest = 0.0
    for name in [n + ".json" for n in CURATED] + ["board.json"]:
        try:
            newest = max(newest, os.path.getmtime(os.path.join(DATA_DIR, name)))
        except OSError:
            continue
    return newest


def build_data_payload():
    stamp = data_stamp()
    if _payload_cache["stamp"] == stamp and _payload_cache["body"] is not None:
        return _payload_cache["body"]

    payload = {"generated_at": datetime.now(timezone.utc).isoformat()}
    for name in CURATED:
        try:
            payload[name] = _load(name + ".json")
        except Exception as exc:  # noqa: BLE001 - reported, not fatal
            payload[name] = None
            payload.setdefault("errors", {})[name] = str(exc)
    try:
        doc = _load("board.json")
        for key in ("board", "clocks", "no_clock", "summary", "errors"):
            payload[key] = doc.get(key)
        payload["board_fetched_at"] = doc.get("fetched_at")
    except Exception as exc:  # noqa: BLE001 - the page renders an explicit gap
        payload["board"] = []
        payload["clocks"] = []
        payload.setdefault("errors", {})["board"] = str(exc)

    _payload_cache["stamp"] = stamp
    _payload_cache["body"] = payload
    return payload


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code, body, cache="no-cache"):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/health":
            # Probe the dependency, not the process: no board, not healthy.
            try:
                doc = _load("board.json")
                summary = doc.get("summary", {})
                self._send(200, {
                    "status": "ok",
                    "trackers": summary.get("trackers"),
                    "live": summary.get("live"),
                    "stale": summary.get("stale"),
                    "signals": summary.get("signals"),
                    "signal_ids": summary.get("signal_ids"),
                    "clocks": len(doc.get("clocks", [])),
                    "errors": len(doc.get("errors", {})),
                    "fetched_at": doc.get("fetched_at"),
                })
            except Exception as exc:  # noqa: BLE001 - absent data IS the unhealthy case
                self._send(503, {"status": "no data", "error": str(exc)})
        elif path == "/api/data":
            self._send(200, build_data_payload(),
                       cache="public, max-age=300, must-revalidate")
        elif path == "/api/status":
            with _lock:
                snapshot = dict(_state)
            snapshot["econcore"] = econcore.VERSION
            self._send(200, snapshot)
        else:
            self._send(404, {"error": "not found"})

    def log_message(self, fmt, *args):
        return


def main():
    if "--refresh" in sys.argv:
        build_board()
        return
    if "--once" in sys.argv:
        build_board(dry=True)
        return

    print("econ updater starting (schedule: host cron)", flush=True)

    def warm():
        for attempt in range(1, WARM_ATTEMPTS + 1):
            try:
                payload = build_board()
                errors = payload.get("errors", {})
                if not errors:
                    return
                reason = "%d tracker(s) unreachable: %s" % (
                    len(errors), ", ".join(sorted(errors)))
            except Exception as exc:  # noqa: BLE001 - server must come up regardless
                reason = "build failed: %s" % exc
            if attempt == WARM_ATTEMPTS:
                print("warm build giving up after %d attempts (%s)"
                      % (attempt, reason), flush=True)
                return
            delay = WARM_BACKOFF[attempt - 1]
            print("warm build attempt %d/%d: %s -- retrying in %ds"
                  % (attempt, WARM_ATTEMPTS, reason, delay), flush=True)
            time.sleep(delay)

    threading.Thread(target=warm, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()


if __name__ == "__main__":
    main()
