#!/usr/bin/env python3
"""The launchpad: one page, opened whenever, that says what the box did in the last 24 hours and
what state it is in now. Pulls one read-only snapshot through ops/box/run.sh (the extractor is
ops/box/launchpad_extract.py, sent on stdin so it needs no release), writes the JSON and a
self-contained dark HTML page under data/launchpad/, and opens it.

    python3 ops/launchpad.py                 # pull, render, open
    python3 ops/launchpad.py --no-open       # pull, render
    python3 ops/launchpad.py --every 300     # keep refreshing (a small SSM read each time)
    python3 ops/launchpad.py --from FILE     # render a saved snapshot (no box access)

Read-only on the box; the page carries no secrets (the extractor drops the override signature and
shortens wallet addresses). Publishing the page as a private Artifact is the agent's step after a
run (`--no-open` then hand the HTML over).
"""
from __future__ import annotations

import argparse
import html
import json
import os
import subprocess
import sys
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kernel.paths import DATA_ROOT  # noqa: E402

BEGIN, END = "===JANUS_JSON_BEGIN===", "===JANUS_JSON_END==="
OUT_DIR = DATA_ROOT / "launchpad"
MX = timezone(timedelta(hours=-6))   # Mexico City (no DST since 2022)


# ── pull ─────────────────────────────────────────────────────────────────────

def box_script() -> str:
    src = (ROOT / "ops" / "box" / "launchpad_extract.py").read_text()
    return ("sudo -u janus JANUS_DATA_ROOT=/srv/janus JANUS_HOST=box JANUS_REPO=/opt/janus "
            "/opt/janus/.venv/bin/python3 - <<'JANUS_LAUNCHPAD_PY'\n" + src + "\nJANUS_LAUNCHPAD_PY\n")


def parse_snapshot(text: str) -> dict:
    """The JSON between the sentinels; run.sh may prepend `status=` and append a stderr tail."""
    a, b = text.find(BEGIN), text.find(END)
    if a < 0 or b < 0 or b < a:
        raise ValueError("no snapshot in the box's output: " + text[-300:])
    body = text[a + len(BEGIN):b].strip()
    if body.startswith("{"):
        return json.loads(body)
    import base64
    import zlib
    return json.loads(zlib.decompress(base64.b64decode(body)).decode())


def pull() -> dict:
    p = subprocess.run(["bash", str(ROOT / "ops" / "box" / "run.sh")], input=box_script(), capture_output=True, text=True, timeout=400)
    return parse_snapshot(p.stdout)


# ── render ───────────────────────────────────────────────────────────────────

def _t(ts, fmt="%H:%M:%SZ") -> str:
    if not ts:
        return "—"
    return datetime.fromtimestamp(float(ts), timezone.utc).strftime(fmt)


def _ago(ts, now) -> str:
    if not ts:
        return "—"
    s = int(now - float(ts))
    return f"{s}s" if s < 90 else f"{s // 60}m" if s < 5400 else f"{s // 3600}h{(s % 3600) // 60:02d}"


def _usd(x, sign=True) -> str:
    if x is None:
        return "—"
    x = float(x)
    s = f"{x:+,.2f}" if sign else f"{x:,.2f}"
    return "$" + s.replace("$", "")


def _cls_usd(x) -> str:
    return "pos" if (x or 0) > 0.0005 else "neg" if (x or 0) < -0.0005 else "flat"


def _gib(n) -> str:
    return "—" if n is None else f"{n / 2 ** 30:.1f}G"


def _esc(s) -> str:
    return html.escape("" if s is None else str(s))


def _sparkline(series: list, width=220, height=34, cap=5.0) -> str:
    pts = [float(v[1] or 0) for v in series if v and v[1] is not None]
    if len(pts) < 2:
        return ""
    step = width / (len(pts) - 1)
    ys = [height - 2 - min(p, cap) / cap * (height - 4) for p in pts]
    poly = " ".join(f"{i * step:.1f},{y:.1f}" for i, y in enumerate(ys))
    area = f"0,{height - 2} " + poly + f" {(len(pts) - 1) * step:.1f},{height - 2}"
    halt = height - 2 - (height - 4)
    end_cls = "bad" if pts[-1] >= cap else "warn" if pts[-1] >= 2 else "ok"
    return (f'<svg class="spark" viewBox="0 0 {width} {height}" width="{width}" height="{height}">'
            f'<line x1="0" y1="{halt:.1f}" x2="{width}" y2="{halt:.1f}" class="spark-halt"/>'
            f'<polygon points="{area}" class="spark-area"/><polyline points="{poly}" class="spark-line"/>'
            f'<circle cx="{(len(pts) - 1) * step:.1f}" cy="{ys[-1]:.1f}" r="2.4" class="spark-end {end_cls}"/></svg>')


def render(snap: dict) -> str:
    now = float(snap.get("as_of") or time.time())
    sysd = snap.get("system") or {}
    units = sysd.get("units") or {}
    lane = units.get("janus-live-stream") or {}
    ov = snap.get("override") or {}
    caps = ov.get("caps") or {}
    kills = snap.get("kills") or []
    breaker = snap.get("breaker")
    alerts = snap.get("watchdog") or []
    socks = snap.get("sockets") or {}
    disk = (sysd.get("disk") or {}).get("data") or {}
    funnel = snap.get("funnel") or {}
    open_ = snap.get("open") or {}
    trades_ = snap.get("trades") or []
    red = snap.get("redemptions") or {}

    lane_ok = lane.get("active") == "active"
    armed = bool(ov) and ov.get("mode") == "LIMITED_LIVE" and (ov.get("seconds_left") or 0) > 0 and not kills
    status = "TRADING" if lane_ok and armed else "HALTED" if kills or (breaker or {}).get("latched") else "OBSERVING" if lane_ok else "DOWN"
    status_cls = {"TRADING": "ok", "HALTED": "bad", "OBSERVING": "warn", "DOWN": "bad"}[status]

    def badge(text, cls):
        return f'<span class="badge {cls}">{_esc(text)}</span>'

    badges = [badge(status, status_cls)]
    for k in kills:
        badges.append(badge(f"KILL/{k.get('name')}", "bad"))
    if (breaker or {}).get("latched"):
        badges.append(badge("BREAKER", "bad"))
    if ov:
        left = ov.get("seconds_left") or 0
        badges.append(badge(f"{ov.get('mode')} · {int(left // 3600)}h left", "ok" if left > 86400 else "warn" if left > 0 else "bad"))
    lag_now = (socks.get("kalshi") or {}).get("loop_lag_s")
    if lag_now is not None:
        badges.append(badge(f"loop {lag_now:.1f}s", "ok" if lag_now < 2 else "warn" if lag_now < 5 else "bad"))
    if disk:
        pct = disk["used"] / disk["total"] * 100 if disk.get("total") else 0
        badges.append(badge(f"disk {pct:.0f}% · {_gib(disk.get('free'))} free", "ok" if pct < 70 else "warn" if pct < 85 else "bad"))

    # ── system strip
    sock_rows = []
    for v in ("kalshi", "polymarket", "polymarket_user"):
        s = socks.get(v)
        if not s:
            sock_rows.append(f"<tr><td>{v}</td><td class='bad'>no row</td><td></td><td></td><td></td></tr>")
            continue
        ok = s["connected"] and (s["tick_age_s"] or 0) < 180
        sock_rows.append(f"<tr><td>{v}</td><td class='{'ok' if ok else 'bad'}'>{'UP' if s['connected'] else 'DOWN'}</td>"
                         f"<td>{_esc(s['age_s'])}s</td><td>{_esc(s['frames'])}</td><td class='muted'>{_esc(s['last_error'] or '')}</td></tr>")
    tmr = lambda u: (units.get(u) or {}).get("active", "?")  # noqa: E731
    sys_kv = [
        ("lane", f"<span class='{'ok' if lane_ok else 'bad'}'>{_esc(lane.get('active', '?'))}</span> · restarts {_esc(lane.get('restarts', '?'))} · since {_esc(lane.get('since', '?'))}"),
        ("deployed", f"<code>{_esc((sysd.get('deployed_sha') or '?')[:12])}</code> · override pins <code>{_esc((ov.get('runner_sha') or '?')[:12])}</code>"),
        ("caps", f"${_esc(caps.get('stake_usd'))} / {_esc(caps.get('max_contracts'))} contracts / ${_esc(caps.get('day_notional_usd'))} a day"),
        ("override", f"expires {_esc(ov.get('expires_utc'))} · written {_esc(str(ov.get('written_utc') or '')[:19])}"),
        ("timers", f"redeem {_esc(tmr('janus-pm-redeem.timer'))} · census {_esc(tmr('janus-census.timer'))} · watchdog {_esc(tmr('janus-watchdog.timer'))}"),
        ("box", f"{_esc(sysd.get('host'))} · {_esc(sysd.get('uptime'))} · load {_esc(' '.join(f'{x:.2f}' for x in sysd.get('load') or []))} · mem {_esc((sysd.get('mem_mb') or {}).get('MemAvailable'))} MB free"),
    ]
    alert_html = "".join(f"<li class='{'warn' if 'STALE' in a or 'PRESSURE' in a else 'bad'}'>{_esc(a)}</li>" for a in alerts) or "<li class='ok'>watchdog quiet</li>"

    # ── trades
    trade_rows = []
    for t in trades_:
        st = t.get("settlement") or {}
        pnl = st.get("realized_usd")
        state = t["state"]
        state_cls = "ok" if state in ("RECONCILED", "HEDGED", "SETTLED") else "muted" if state in ("ORDER_UNFILLED",) else "warn" if state == "ORDER_REJECTED" else "bad"
        kalshi = [o for o in t["orders"] if o["venue"] == "kalshi"]
        pm = [o for o in t["orders"] if o["venue"] == "polymarket"]
        first = f"{t['first_filled']:.2f}@{t['first_avg_price']:.3f}" if t.get("first_filled") else "0"
        hedge = f"{t['hedge_filled']:.2f}@{t['hedge_avg_price']:.3f}" if t.get("hedge_filled") else "0"
        secs = f"{(t.get('b_settled_ms') or 0) / 1000:.1f}s" if t.get("b_settled_ms") else "—"
        note = st.get("kind") or ""
        if t.get("revisions"):
            note += f" · revised×{t['revisions']}"
        if t.get("guard_reruns"):
            note += f" · reruns {t['guard_reruns']}"
        if t.get("advance"):
            note += " · L75"
        trade_rows.append(
            f"<tr><td class='muted'>{_t(t['started_utc'])}</td><td><b>{_esc(t['short_name'])}</b> <span class='muted'>{_esc(t['league'])}</span></td>"
            f"<td class='{state_cls}'>{_esc(state)}</td><td>{_esc(t['quantity'])}</td><td>{first}</td><td>{hedge}</td>"
            f"<td class='num'>{len(pm)}/{len(kalshi)}</td><td>{secs}</td>"
            f"<td class='num {_cls_usd(pnl)}'>{_usd(pnl) if pnl is not None else '—'}</td><td class='muted'>{_esc(note)}</td></tr>")
    if not trade_rows:
        trade_rows.append("<tr><td colspan='10' class='muted'>no executions in the last 24 h</td></tr>")

    tiles = [
        ("attempts 24h", funnel.get("attempts", 0), ""),
        ("first-leg fills", funnel.get("first_leg_fills", 0), ""),
        ("covers", funnel.get("covers", 0), ""),
        ("realized 24h", _usd(funnel.get("realized_usd")), _cls_usd(funnel.get("realized_usd"))),
        ("cover-only", _usd(funnel.get("cover_usd")), _cls_usd(funnel.get("cover_usd"))),
        ("profitable prints", funnel.get("profitable_prints", "—"), ""),
        ("events w/ print", funnel.get("events_with_profitable_print", "—"), ""),
        ("today realized", _usd(open_.get("today_realized_usd")), _cls_usd(open_.get("today_realized_usd"))),
    ]
    tile_html = "".join(f"<div class='tile'><div class='k'>{_esc(k)}</div><div class='v {c}'>{_esc(v)}</div></div>" for k, v, c in tiles)
    by_state = ", ".join(f"{k} {v}" for k, v in sorted((funnel.get("by_state") or {}).items(), key=lambda kv: -kv[1]))

    # ── open exposure
    open_rows = []
    for e in open_.get("executions") or []:
        cls = "bad" if e["attention"] else "ok" if e["pending_settlement"] else "warn"
        open_rows.append(f"<tr><td class='muted'>{_t(e['started_utc'])}</td><td><b>{_esc(e['short_name'])}</b></td><td class='{cls}'>{_esc(e['state'])}</td>"
                         f"<td>{_esc(e['first_filled'])}@{_esc(e['first_avg_price'])}</td><td>{_esc(e['hedge_filled'])}@{_esc(e['hedge_avg_price'])}</td>"
                         f"<td class='{'bad' if (e['unhedged'] or 0) >= 1 else ''}'>{_esc(e['unhedged'])}</td></tr>")
    if not open_rows:
        open_rows.append("<tr><td colspan='6' class='muted'>nothing held</td></tr>")
    order_rows = "".join(f"<tr><td class='muted'>{_t(o['submitted_utc'])}</td><td>{_esc(o['venue'])}</td><td>{_esc(o['side'])} {_esc(o['contracts'])}@{_esc(o['price'])}</td>"
                         f"<td class='warn'>{_esc(o['state'])}{' open' if o['open'] else ''}{' settling' if o['settlement_pending'] else ''}</td></tr>"
                         for o in open_.get("orders") or []) or "<tr><td colspan='4' class='muted'>no live orders</td></tr>"
    res_rows = "".join(f"<tr><td>{_esc(r['event_id'])}</td><td>{_esc(r['league'])}</td><td class='num'>{_usd(r['total_usd'], sign=False)}</td><td class='muted'>{_ago(r['created_utc'], now)}</td></tr>"
                       for r in open_.get("reservations") or []) or "<tr><td colspan='4' class='muted'>no open reservations</td></tr>"
    cap = open_.get("day_cap_usd")
    day = open_.get("day_committed_usd") or 0
    day_pct = (day / cap * 100) if cap else 0
    flag_rows = "".join(f"<li><span class='muted'>{_t(f['seen_ts'])}</span> <b>{_esc(f['flag'])}</b> {_esc(f['detail'])}</li>" for f in snap.get("flags") or []) or "<li class='muted'>no flags in 24 h</li>"
    red_html = "—"
    if red:
        red_html = ", ".join(f"{k} {v}" for k, v in (red.get("by_state") or {}).items()) or "none"
        if red.get("last"):
            red_html += "<br><span class='muted'>" + " · ".join(f"{r['state']} {_esc(r['value'])} {_esc(r['detail'])}" for r in red["last"][:2]) + "</span>"

    as_of_mx = datetime.fromtimestamp(now, MX).strftime("%Y-%m-%d %H:%M")
    return f"""<title>Janus Launchpad</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans+Condensed:wght@500;600&display=swap">
<style>
:root {{ --bg:#0b0d10; --panel:#11151a; --line:#232a33; --fg:#d7dde6; --muted:#7c8794; --amber:#f5a623; --green:#3ddc84; --red:#ff5c5c; --blue:#5aa9ff; --yellow:#ffd166; }}
body {{ background:var(--bg); color:var(--fg); font:12.5px/1.45 "IBM Plex Mono", "SF Mono", Menlo, Consolas, monospace; margin:0; padding:14px 16px 30px; font-variant-numeric:tabular-nums; }}
h1, h2, .badge, th, .tile .k, .lbl {{ font-family:"IBM Plex Sans Condensed", "Helvetica Neue", Arial, sans-serif; }}
h1 {{ font-size:15px; letter-spacing:.14em; color:var(--amber); margin:0; text-transform:uppercase; }}
h2 {{ font-size:11px; letter-spacing:.14em; color:var(--amber); text-transform:uppercase; margin:0 0 8px; border-bottom:1px solid var(--line); padding-bottom:4px; }}
.top {{ display:flex; align-items:center; gap:14px; flex-wrap:wrap; margin-bottom:12px; }}
.badge {{ display:inline-block; padding:2px 8px; border:1px solid var(--line); border-radius:3px; font-weight:600; letter-spacing:.06em; }}
.badge.ok {{ color:var(--green); border-color:#1f5a3a; }} .badge.warn {{ color:var(--yellow); border-color:#5a4a1f; }} .badge.bad {{ color:#fff; background:var(--red); border-color:var(--red); }}
.grid {{ display:grid; grid-template-columns: 1.6fr 1fr; gap:14px; }}
@media (max-width: 1100px) {{ .grid {{ grid-template-columns:1fr; }} }}
.panel {{ background:var(--panel); border:1px solid var(--line); border-radius:6px; padding:10px 12px; margin-bottom:14px; }}
table {{ width:100%; border-collapse:collapse; }} th {{ text-align:left; color:var(--muted); font-weight:500; font-size:11px; letter-spacing:.06em; text-transform:uppercase; padding:3px 6px; border-bottom:1px solid var(--line); }}
td {{ padding:4px 6px; border-bottom:1px solid #171c22; vertical-align:top; white-space:nowrap; }} .wrap {{ overflow-x:auto; }}
.num {{ text-align:right; font-variant-numeric:tabular-nums; }} .pos {{ color:var(--green); }} .neg {{ color:var(--red); }} .flat {{ color:var(--muted); }}
.ok {{ color:var(--green); }} .warn {{ color:var(--yellow); }} .bad {{ color:var(--red); }} .muted {{ color:var(--muted); }}
code {{ color:var(--blue); }} .kv td:first-child {{ color:var(--muted); width:88px; }}
.tiles {{ display:grid; grid-template-columns:repeat(4, 1fr); gap:8px; margin:6px 0 10px; }}
.tile {{ background:#0e1216; border:1px solid var(--line); border-radius:4px; padding:6px 8px; }} .tile .k {{ color:var(--muted); font-size:10.5px; letter-spacing:.08em; text-transform:uppercase; }} .tile .v {{ font-size:18px; font-weight:600; margin-top:2px; }}
ul {{ margin:0; padding-left:16px; }} li {{ margin:2px 0; }}
.spark {{ display:block; }} .spark-line {{ fill:none; stroke:var(--blue); stroke-width:1.5; }} .spark-area {{ fill:var(--blue); opacity:.12; }} .spark-halt {{ stroke:var(--red); stroke-width:.6; stroke-dasharray:3 3; }}
.spark-end.ok {{ fill:var(--green); }} .spark-end.warn {{ fill:var(--yellow); }} .spark-end.bad {{ fill:var(--red); }}
.bar {{ height:6px; background:#0e1216; border:1px solid var(--line); border-radius:3px; overflow:hidden; }} .bar i {{ display:block; height:100%; background:var(--amber); }}
.foot {{ color:var(--muted); margin-top:6px; font-size:11px; }}
</style>
<div class="top"><h1>Janus · Launchpad</h1>{''.join(badges)}<span class="muted">as of {_t(now, '%Y-%m-%d %H:%M:%SZ')} · {as_of_mx} MX</span></div>
<div class="grid">
<div>
  <div class="panel"><h2>System</h2>
    <table class="kv">{''.join(f"<tr><td>{_esc(k)}</td><td>{v}</td></tr>" for k, v in sys_kv)}</table>
    <div style="display:flex;gap:16px;align-items:flex-start;margin-top:8px;flex-wrap:wrap">
      <div class="wrap" style="flex:1;min-width:360px"><table><tr><th>socket</th><th>state</th><th>age</th><th>frames</th><th>last error</th></tr>{''.join(sock_rows)}</table></div>
      <div><div class="muted" style="font-size:10.5px;letter-spacing:.08em">LOOP LAG · last hour · red = 5 s halt</div>{_sparkline(snap.get('lag_series') or [])}</div>
    </div>
    <div style="margin-top:8px"><ul>{alert_html}</ul></div>
  </div>
  <div class="panel"><h2>Executions · last 24 h</h2>
    <div class="tiles">{tile_html}</div>
    <div class="muted" style="margin-bottom:6px">by state: {_esc(by_state) or '—'}</div>
    <div class="wrap"><table><tr><th>utc</th><th>event</th><th>state</th><th>qty</th><th>first leg</th><th>hedge</th><th>orders pm/k</th><th>hedged in</th><th class="num">p&amp;l</th><th>note</th></tr>{''.join(trade_rows)}</table></div>
  </div>
</div>
<div>
  <div class="panel"><h2>Open exposure</h2>
    <div class="wrap"><table><tr><th>utc</th><th>event</th><th>state</th><th>first</th><th>hedge</th><th>unhedged</th></tr>{''.join(open_rows)}</table></div>
    <div class="muted" style="margin:8px 0 3px">day committed {_usd(day, sign=False)} of {_usd(cap, sign=False) if cap else '—'} · open reservations {_usd(open_.get('open_reservation_usd'), sign=False)}</div>
    <div class="bar"><i style="width:{min(100, day_pct):.0f}%"></i></div>
  </div>
  <div class="panel"><h2>Live orders</h2><div class="wrap"><table><tr><th>utc</th><th>venue</th><th>order</th><th>state</th></tr>{order_rows}</table></div></div>
  <div class="panel"><h2>Reservations</h2><div class="wrap"><table><tr><th>event</th><th>league</th><th class="num">usd</th><th>age</th></tr>{res_rows}</table></div></div>
  <div class="panel"><h2>Redemptions</h2>{red_html}</div>
  <div class="panel"><h2>Lane flags · 24 h</h2><ul>{flag_rows}</ul></div>
</div>
</div>
<div class="foot">read-only snapshot · {_esc(snap.get('data_root'))} · deployed {_esc((sysd.get('deployed_sha') or '')[:12])} · python3 ops/launchpad.py to refresh</div>
"""


# ── cli ──────────────────────────────────────────────────────────────────────

def write(snap: dict, out_dir: Path = OUT_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "latest.json").write_text(json.dumps(snap, indent=1, default=str))
    page = out_dir / "launchpad.html"
    page.write_text(render(snap))
    return page


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-open", action="store_true")
    ap.add_argument("--every", type=float, default=0.0, help="seconds between refreshes; 0 = once")
    ap.add_argument("--from", dest="src", type=Path, help="render this saved snapshot instead of pulling")
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    a = ap.parse_args()
    opened = False
    while True:
        t0 = time.time()
        try:
            snap = json.loads(a.src.read_text()) if a.src else pull()
        except Exception as exc:  # noqa: BLE001
            print(f"pull failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            if not a.every:
                return 1
            time.sleep(a.every)
            continue
        page = write(snap, a.out)
        f = snap.get("funnel") or {}
        print(f"{page}  ({time.time() - t0:.1f}s)  attempts={f.get('attempts')} fills={f.get('first_leg_fills')} "
              f"covers={f.get('covers')} realized={f.get('realized_usd')} kills={[k.get('name') for k in snap.get('kills') or []]}")
        if not a.no_open and not opened:
            webbrowser.open(page.as_uri())
            opened = True
        if not a.every:
            return 0
        time.sleep(max(1.0, a.every - (time.time() - t0)))


if __name__ == "__main__":
    raise SystemExit(main())
