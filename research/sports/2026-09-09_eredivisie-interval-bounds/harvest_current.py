#!/usr/bin/env python3
"""Archive the operator-requested current canonical rules harvest; no prices or orders."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
ROOT = Path('/Volumes/Kilos/janus/research/eredivisie-L50')


if __name__ == '__main__':
    results = []
    for hours in (48, 168):
        started = datetime.now(timezone.utc)
        command = ['python3', 'ops/harvest_templates.py', '--league', 'ere', '--pre-hours', str(hours)]
        completed = subprocess.run(command, cwd=REPO, text=True, capture_output=True)
        path = ROOT / ('current-harvest-' + str(hours) + '-' + started.strftime('%Y%m%dT%H%M%S%fZ') + '.txt')
        content = completed.stdout + '\nSTDERR:\n' + completed.stderr
        with path.open('x') as stream:
            stream.write(content)
        result = {'command': command, 'started_at': started.isoformat(),
                  'finished_at': datetime.now(timezone.utc).isoformat(), 'returncode': completed.returncode,
                  'path': str(path), 'sha256': hashlib.sha256(content.encode()).hexdigest()}
        results.append(result)
        print(json.dumps(result, sort_keys=True), flush=True)
        print(content, flush=True)
    output = HERE / 'current_harvest.json'
    with output.open('x') as stream:
        json.dump({'id': 'L50', 'purpose': 'Current template verification after registered evidence; no rate or cap changes',
                   'runs': results}, stream, indent=2, sort_keys=True)
        stream.write('\n')
