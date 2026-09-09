#!/usr/bin/env python3
"""Archive the prewritten read-only Maximus journal query, including historical venue raw JSON."""
import hashlib
import json
from pathlib import Path
import subprocess
import time

HERE = Path(__file__).resolve().parent
repo = HERE.parents[2]
source = HERE / 'inspect_maximus.sh'
result = subprocess.run(['bash', str(repo / 'ops/box/run.sh')], input=source.read_bytes(),
                        capture_output=True, check=True)
raw = result.stdout.strip()
json.loads(raw)
root = Path('/Volumes/Kilos/janus/accounting/L52') / (time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '_maximus_journal')
root.mkdir(mode=0o700)
with (root / 'journal.json').open('xb') as output:
    output.write(raw)
metadata = {'kind': 'read-only local execution journal containing historical venue responses',
            'observed_utc': time.time(), 'raw_sha256': hashlib.sha256(raw).hexdigest(),
            'script_sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
with (root / 'journal.meta.json').open('x') as output:
    json.dump(metadata, output, indent=2, sort_keys=True)
print(json.dumps({'archive': str(root), **metadata}))
