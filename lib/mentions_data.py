#!/usr/bin/env python3
"""Build and load the cross-venue MENTIONS corpus, with the holdout enforced in code.

    python3 lib/mentions_data.py --build      # crawl both venues' settled mention markets
    python3 lib/mentions_data.py              # summarise what is on disk

Mentions markets ("will <person> say <word> during <event>?") are structurally the most promising
cross-venue category found so far:
  * they resolve on a DISCRETE, verifiable utterance -- no price index, so none of the oracle
    wedge that made the BTC trade worth 94.30c instead of 100c;
  * they are short-dated (days to weeks), so capital recycles;
  * both venues list them, and Kalshi has deep settled history (1,200 settled markets on
    KXTRUMPMENTION alone, back to 2026-05-20);
  * the venues quote them completely differently -- measured 2026-07-25, Kalshi ran bid 0.04 /
    ask 0.78 while Polymarket ran bid 0.13 / ask 0.14 on comparable markets.

THE HOLDOUT IS ENFORCED HERE, NOT BY CONVENTION. `load()` defaults to the characterization era.
Reading the sealed era requires era="holdout" AND allow_holdout=True, and every such call is
appended to research/mentions/holdout_access.log. See research/mentions/HOLDOUT.md.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.fetch import Client, OffsetCap  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "mentions"
LOG = ROOT / "research" / "mentions" / "holdout_access.log"

KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
GAMMA = "https://gamma-api.polymarket.com"

#: Everything settling at/after this instant is SEALED. Declared 2026-07-25 before any outcome
#: was read. See research/mentions/HOLDOUT.md.
HOLDOUT_START_UTC = "2026-07-25T00:00:00Z"
HOLDOUT_START_TS = dt.datetime.fromisoformat(HOLDOUT_START_UTC.replace("Z", "+00:00")).timestamp()

PM_MENTION_RX = re.compile(r"\bsay\b|\bsays\b|\bmention\b|\bmentions\b|utter", re.I)


def iso_ts(s):
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


# ══════════════════════════════════════════════════════════════════════════
# Build
# ══════════════════════════════════════════════════════════════════════════

def kalshi_mention_series(c: Client) -> dict:
    d = c.get_json(f"{KALSHI}/series", params={"limit": 1000})
    return {s["ticker"]: s for s in d.get("series", []) if s.get("category") == "Mentions"}


def build_kalshi(c: Client) -> list[dict]:
    series = kalshi_mention_series(c)
    print(f"  kalshi mention series: {len(series)}")
    rows = []
    for i, (st, s) in enumerate(sorted(series.items()), 1):
        for status in ("settled", "open"):
            try:
                for page in c.paginate_cursor(
                        f"{KALSHI}/markets",
                        {"series_ticker": st, "status": status, "limit": 1000},
                        key="markets", max_pages=8):
                    for m in page:
                        cts = iso_ts(m.get("close_time"))
                        res = m.get("result")
                        rows.append({
                            "venue": "kalshi", "series": st,
                            "series_title": s.get("title"),
                            "ticker": m.get("ticker"),
                            "event_ticker": m.get("event_ticker"),
                            "title": m.get("title"),
                            "term": m.get("yes_sub_title"),
                            "rules": m.get("rules_primary"),
                            "status": m.get("status"),
                            "result": res if res in ("yes", "no") else None,
                            "outcome": (1 if res == "yes" else 0) if res in ("yes", "no") else None,
                            "open_time": m.get("open_time"), "close_time": m.get("close_time"),
                            "close_ts": cts,
                            "yes_bid": _f(m.get("yes_bid_dollars")),
                            "yes_ask": _f(m.get("yes_ask_dollars")),
                            "volume": _f(m.get("volume_fp")),
                            "open_interest": _f(m.get("open_interest_fp")),
                            "fee_type": s.get("fee_type"),
                            "fee_multiplier": s.get("fee_multiplier"),
                            "era": era_of(cts),
                        })
            except Exception as e:  # noqa: BLE001
                print(f"    ! {st}/{status}: {type(e).__name__}: {e}")
        if i % 15 == 0:
            print(f"    ...{i}/{len(series)} series, {len(rows)} markets")
    return rows


def build_pm(c: Client) -> list[dict]:
    seen = {}
    for closed in ("true", "false"):
        for tag in ("mentions", "politics", "pop-culture", "economics", "business", "tech"):
            try:
                for page in c.paginate_offset(
                        f"{GAMMA}/events", {"closed": closed, "tag_slug": tag}, limit=100):
                    for e in page:
                        seen[e["id"]] = e
            except OffsetCap:
                pass
    # date-slice the recent past too, so settled mention markets are reachable
    today = dt.datetime.now(dt.UTC).date()
    d = today - dt.timedelta(days=90)
    while d < today + dt.timedelta(days=45):
        hi = d + dt.timedelta(days=5)
        for closed in ("true", "false"):
            try:
                for page in c.paginate_offset(
                        f"{GAMMA}/events",
                        {"closed": closed, "end_date_min": d.isoformat(),
                         "end_date_max": hi.isoformat()}, limit=100):
                    for e in page:
                        seen[e["id"]] = e
            except OffsetCap:
                pass
        d = hi
    print(f"  pm events scanned: {len(seen)}")

    rows = []
    for e in seen.values():
        et = e.get("title") or ""
        for m in (e.get("markets") or []):
            q = m.get("question") or ""
            if not PM_MENTION_RX.search(q + " " + et):
                continue
            ets = iso_ts(m.get("endDateIso") or m.get("endDate"))
            prices = m.get("outcomePrices")
            if isinstance(prices, str):
                try:
                    prices = json.loads(prices)
                except ValueError:
                    prices = None
            outcome = None
            if m.get("closed") and prices:
                try:
                    p0 = float(prices[0])
                    if p0 >= 0.99:
                        outcome = 1
                    elif p0 <= 0.01:
                        outcome = 0
                except (ValueError, IndexError, TypeError):
                    pass
            rows.append({
                "venue": "polymarket", "event_slug": e.get("slug"), "event_title": et,
                "condition_id": m.get("conditionId"), "question": q,
                "term": _term_from_question(q),
                "rules": m.get("description"),
                "closed": m.get("closed"), "outcome": outcome,
                "end_date": m.get("endDateIso") or m.get("endDate"), "close_ts": ets,
                "best_bid": m.get("bestBid"), "best_ask": m.get("bestAsk"),
                "liquidity": m.get("liquidityNum"), "volume": m.get("volumeNum"),
                "era": era_of(ets),
            })
    return rows


def _f(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _term_from_question(q: str) -> str | None:
    m = re.search(r'"([^"]+)"', q or "")
    if m:
        return m.group(1)
    m = re.search(r"\bsay\s+(.+?)\s+(?:during|in|at|on)\b", q or "", re.I)
    return m.group(1) if m else None


def era_of(close_ts) -> str:
    if close_ts is None:
        return "unknown"
    return "holdout" if close_ts >= HOLDOUT_START_TS else "characterization"


# ══════════════════════════════════════════════════════════════════════════
# Load — the holdout guard
# ══════════════════════════════════════════════════════════════════════════

def load(venue: str, *, era: str = "characterization", allow_holdout: bool = False,
         reason: str = "") -> list[dict]:
    """Load mention markets. DEFAULTS TO THE CHARACTERIZATION ERA.

    era="holdout" requires allow_holdout=True and is logged. era="all" is likewise gated, because
    "all" silently includes the sealed era — the exact way a holdout gets spent by accident.
    """
    # ── GUARD FIRST, IO SECOND ──────────────────────────────────────────
    # Order matters. If the file check ran first, a missing file would raise FileNotFoundError and
    # mask the permission failure — so the guard would look untested and, worse, someone debugging
    # the "missing file" error could satisfy it by building the data and then sail straight past a
    # gate that never actually fired. Validate the era, then check permission, then touch disk.
    if era not in ("characterization", "holdout", "all"):
        raise ValueError(f"unknown era {era!r}")
    if era in ("holdout", "all") and not allow_holdout:
        raise PermissionError(
            f"era={era!r} touches the SEALED mentions holdout ({HOLDOUT_START_UTC}+). "
            "Pass allow_holdout=True only with an explicit per-run user approval that names "
            "this holdout. See research/mentions/HOLDOUT.md.")

    path = DATA / f"{venue}_mentions.json"
    if not path.exists():
        raise FileNotFoundError(f"{path} — run `python3 lib/mentions_data.py --build` first")
    rows = json.loads(path.read_text())

    if era == "characterization":
        return [r for r in rows if r.get("era") == "characterization"]

    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        f.write(f"{dt.datetime.now(dt.UTC).isoformat()}\tvenue={venue}\tera={era}\t"
                f"reason={reason or 'UNSTATED'}\n")
    return rows if era == "all" else [r for r in rows if r.get("era") == "holdout"]


def selftest_guard() -> None:
    """Prove the guard fires, and fires FIRST. A monitor that never emitted is untested."""
    for era in ("holdout", "all"):
        try:
            load("kalshi", era=era)
            raise AssertionError(f"guard did not fire for era={era!r}")
        except PermissionError:
            pass
        except FileNotFoundError as e:
            raise AssertionError(f"IO preceded the guard for era={era!r}") from e
    try:
        load("kalshi", era="nonsense")
        raise AssertionError("bad era accepted")
    except ValueError:
        pass
    print(f"holdout guard selftest OK (sealed era = {HOLDOUT_START_UTC}+, blocked before IO)")


def summarize() -> dict:
    out = {"holdout_start_utc": HOLDOUT_START_UTC}
    for venue in ("kalshi", "polymarket"):
        p = DATA / f"{venue}_mentions.json"
        if not p.exists():
            out[venue] = {"built": False}
            continue
        rows = json.loads(p.read_text())
        eras = Counter(r.get("era") for r in rows)
        ch = [r for r in rows if r.get("era") == "characterization"]
        lab = [r for r in ch if r.get("outcome") is not None]
        out[venue] = {
            "built": True, "n_total": len(rows), "by_era": dict(eras),
            "characterization_n": len(ch),
            "characterization_labelled": len(lab),
            "base_rate_yes": round(sum(r["outcome"] for r in lab) / len(lab), 4) if lab else None,
            "n_series_or_events": len({r.get("series") or r.get("event_title") for r in ch}),
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    a = ap.parse_args()
    DATA.mkdir(parents=True, exist_ok=True)
    if a.build:
        ck = Client("kalshi", rate=6.0, burst=10.0, cache_dir=DATA / "_cache_k")
        cp = Client("pm", rate=5.0, burst=8.0, cache_dir=DATA / "_cache_p")
        print("building kalshi mentions...")
        k = build_kalshi(ck)
        (DATA / "kalshi_mentions.json").write_text(json.dumps(k))
        print(f"  kalshi rows: {len(k)}  ({ck.stats})")
        print("building polymarket mentions...")
        p = build_pm(cp)
        (DATA / "polymarket_mentions.json").write_text(json.dumps(p))
        print(f"  pm rows: {len(p)}  ({cp.stats})")
    print(json.dumps(summarize(), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
