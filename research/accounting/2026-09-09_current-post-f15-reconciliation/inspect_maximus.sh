sudo -u janus env PYTHONDONTWRITEBYTECODE=1 /opt/janus/.venv/bin/python3 - <<'PY'
import json, sqlite3, time
from pathlib import Path
con = sqlite3.connect('file:/srv/janus/tuples/tuples.sqlite?mode=ro', uri=True, timeout=10)
con.row_factory = sqlite3.Row
oid = '0x8b43f15c3eb76e3e5a08e625015d2e8093cc0184885ba00d143cd6b4461e959a'
orders = [dict(x) for x in con.execute('select * from orders where venue_order_id=?', (oid,))]
out = {'observed_utc': time.time(), 'orders': orders, 'executions': [], 'events': []}
for row in orders:
    cid = row['client_order_id']
    out['executions'].extend(dict(x) for x in con.execute('select * from executions where first_client_id=?', (cid,)))
    out['events'].extend(dict(x) for x in con.execute('select * from order_events where client_order_id=?', (cid,)))
out['kills'] = {name: {'exists': (Path('/srv/janus/kill') / name).exists(),
               'contents': (Path('/srv/janus/kill') / name).read_text() if (Path('/srv/janus/kill') / name).exists() else None}
               for name in ('live', 'all')}
arm = json.loads(Path('/srv/janus/kill/arming_override.json').read_text())
out['arm'] = arm
print(json.dumps(out, separators=(',', ':')))
PY
