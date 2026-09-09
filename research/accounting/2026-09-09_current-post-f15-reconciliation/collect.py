#!/usr/bin/env python3
"""L52: archive raw GET responses through existing SSM, with no remote file writes.

Authenticated Polymarket construction deliberately derives an EXISTING API key with GET;
the production transport's create_or_derive_api_key (which first POSTs) is not used.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import time


REMOTE = r'''
import base64, gzip, hashlib, json, os, time, urllib.request, urllib.parse, urllib.error
from pathlib import Path
cfg = json.loads(CONFIG)
source = cfg['source']
params = cfg['params']
headers = {'Accept': 'application/json', 'User-Agent': 'Janus-L52-readonly-audit'}
if source.startswith('kalshi_'):
    from nodes.exec_kalshi.client import sign, API, PROD_BASE
    from nodes.stream_kalshi.stream import load_private_key
    route = {'kalshi_fills': '/portfolio/fills', 'kalshi_settlements': '/portfolio/settlements',
             'kalshi_positions': '/portfolio/positions', 'kalshi_balance': '/portfolio/balance',
             'kalshi_deposits': '/portfolio/deposits', 'kalshi_withdrawals': '/portfolio/withdrawals',
             'kalshi_historical_cutoff': '/historical/cutoff', 'kalshi_historical_fills': '/historical/fills'}[source]
    path = API + route
    ts, signature = sign(load_private_key(Path(os.environ['JANUS_KALSHI_PRIVATE_KEY_PATH'])), 'GET', path)
    headers.update({'KALSHI-ACCESS-KEY': os.environ['JANUS_KALSHI_API_KEY'],
                    'KALSHI-ACCESS-TIMESTAMP': ts, 'KALSHI-ACCESS-SIGNATURE': signature})
    url = PROD_BASE + path
elif source.startswith('pm_clob_'):
    from py_clob_client_v2.client import ClobClient
    from py_clob_client_v2.endpoints import TRADES, GET_BALANCE_ALLOWANCE
    keypath = Path(os.environ['JANUS_PM_WALLET_KEY_PATH'])
    assert keypath.stat().st_mode & 0o077 == 0, 'wallet key permissions'
    client = ClobClient('https://clob.polymarket.com', 137, key=keypath.read_text().strip(),
          signature_type=int(os.environ['JANUS_PM_SIGNATURE_TYPE']), funder=os.environ['JANUS_PM_FUNDER'])
    client.set_api_creds(client.derive_api_key())  # GET only, no create fallback
    path = TRADES if source == 'pm_clob_trades' else GET_BALANCE_ALLOWANCE
    if source == 'pm_clob_maximus_order':
        from py_clob_client_v2.endpoints import GET_ORDER
        path = GET_ORDER + '0x8b43f15c3eb76e3e5a08e625015d2e8093cc0184885ba00d143cd6b4461e959a'
    headers.update(client._l2_headers('GET', path))
    if source == 'pm_clob_balance':
        params.update({'signature_type': int(os.environ['JANUS_PM_SIGNATURE_TYPE']), 'asset_type': 'COLLATERAL'})
    url = client.host + path
else:
    path = {'pm_activity': '/activity', 'pm_positions': '/positions', 'pm_closed_positions': '/closed-positions',
            'pm_snapshot': '/v1/accounting/snapshot'}[source]
    params['user'] = os.environ['JANUS_PM_FUNDER']
    url = 'https://data-api.polymarket.com' + path
request_url = url + ('?' + urllib.parse.urlencode(params) if params else '')
started = time.time()
try:
    with urllib.request.urlopen(urllib.request.Request(request_url, headers=headers, method='GET'), timeout=25) as response:
        raw, status = response.read(), response.status
        date = response.headers.get('Date')
except urllib.error.HTTPError as error:
    raw, status, date = error.read(), error.code, error.headers.get('Date')
body = base64.b64encode(gzip.compress(raw, mtime=0)).decode()
envelope = {'source': source, 'url': url, 'params': params, 'method': 'GET', 'status': status,
            'started_utc': started, 'received_utc': time.time(), 'server_date': date,
            'raw_sha256': hashlib.sha256(raw).hexdigest(), 'raw_bytes': len(raw),
            'chunks': (len(body) + 17999) // 18000,
            'gzip_b64': body[cfg['chunk'] * 18000:(cfg['chunk'] + 1) * 18000]}
print(json.dumps(envelope, separators=(',', ':')))
'''


SOURCES = {
    'kalshi_fills': ({'limit': 50}, 'fills', 'cursor'),
    'kalshi_settlements': ({'limit': 50}, 'settlements', 'cursor'),
    'kalshi_positions': ({'limit': 50}, 'market_positions', 'cursor'),
    'kalshi_balance': ({}, None, None),
    'kalshi_deposits': ({'limit': 50}, 'deposits', 'cursor'),
    'kalshi_withdrawals': ({'limit': 50}, 'withdrawals', 'cursor'),
    'kalshi_historical_cutoff': ({}, None, None),
    'kalshi_historical_fills': ({'limit': 50}, 'fills', 'cursor'),
    'pm_clob_trades': ({'next_cursor': 'MA=='}, 'data', 'next_cursor'),
    'pm_clob_balance': ({}, None, None),
    'pm_clob_maximus_order': ({}, None, None),
    'pm_activity': ({'limit': 50, 'offset': 0, 'sortBy': 'TIMESTAMP', 'sortDirection': 'ASC',
                     'excludeDepositsWithdrawals': 'false'}, '', 'offset'),
    'pm_positions': ({'limit': 50, 'offset': 0, 'sizeThreshold': 0}, '', 'offset'),
    'pm_closed_positions': ({'limit': 50, 'offset': 0, 'sortBy': 'TIMESTAMP', 'sortDirection': 'ASC'}, '', 'offset'),
    'pm_snapshot': ({}, None, None),
}


def aws(*args):
    proc = subprocess.run(['aws', 'ssm', *args, '--region', 'mx-central-1', '--output', 'json'],
                          capture_output=True, text=True, check=True)
    return json.loads(proc.stdout)


def request_chunk(source, params, chunk=0):
    config = json.dumps({'source': source, 'params': params, 'chunk': chunk})
    code = 'CONFIG = ' + repr(config) + '\n' + REMOTE
    encoded = base64.b64encode(code.encode()).decode()
    invocation = 'import base64; exec(base64.b64decode(' + repr(encoded) + '))'
    command = 'set -a; . /run/janus/janus.env; set +a; cd /opt/janus; PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3 -c ' + shlex.quote(invocation)
    shell = 'sudo -u janus bash -c ' + shlex.quote(command)
    response = aws('send-command', '--instance-ids', 'i-0a8c073c72dcdae11',
        '--document-name', 'AWS-RunShellScript', '--parameters', json.dumps({'commands': [shell]}))
    command_id = response['Command']['CommandId']
    deadline = time.monotonic() + 100
    while time.monotonic() < deadline:
        try:
            result = aws('get-command-invocation', '--command-id', command_id,
                         '--instance-id', 'i-0a8c073c72dcdae11')
        except subprocess.CalledProcessError:
            time.sleep(2)
            continue
        if result['Status'] in ('Success', 'Failed', 'Cancelled', 'TimedOut'):
            if result['Status'] != 'Success':
                raise RuntimeError(f"SSM {result['Status']} for {source}; command {command_id}")
            envelope = json.loads(result['StandardOutputContent'])  # truncation fails closed
            envelope['ssm_command_id'] = command_id
            return envelope
        time.sleep(2)
    raise TimeoutError(f'SSM response unavailable: {command_id}')


def request(source, params):
    metadata = request_chunk(source, params)
    encoded = metadata.pop('gzip_b64')
    command_ids = [metadata['ssm_command_id']]
    for chunk in range(1, metadata['chunks']):
        part = request_chunk(source, params, chunk)
        if part['raw_sha256'] != metadata['raw_sha256'] or part['chunks'] != metadata['chunks']:
            raise RuntimeError('Source changed during chunk retrieval; no raw response reconstructed')
        encoded += part['gzip_b64']
        command_ids.append(part['ssm_command_id'])
    raw = gzip.decompress(base64.b64decode(encoded))
    assert hashlib.sha256(raw).hexdigest() == metadata['raw_sha256']
    assert len(raw) == metadata['raw_bytes']
    metadata['ssm_command_ids'] = command_ids
    return raw, metadata


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source', choices=sorted(SOURCES))
    args = parser.parse_args()
    root = Path('/Volumes/Kilos/janus/accounting/L52')
    root.mkdir(parents=True, exist_ok=True)
    run = root / (time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '_' + args.source)
    run.mkdir(mode=0o700)
    params, rowkey, paging = SOURCES[args.source]
    params = dict(params)
    seen_cursors = set()
    count = 0
    for number in range(100):
        raw, metadata = request(args.source, params)
        stem = f'{number:04d}'
        suffix = '.zip' if args.source == 'pm_snapshot' and metadata['status'] == 200 else '.json'
        with (run / (stem + suffix)).open('xb') as output:
            output.write(raw)
        with (run / (stem + '.meta.json')).open('x') as output:
            json.dump(metadata, output, indent=2, sort_keys=True)
        if metadata['status'] != 200:
            raise RuntimeError(f"HTTP {metadata['status']}; preserved at {run}")
        payload = {} if suffix == '.zip' else json.loads(raw)
        rows = payload if rowkey == '' else payload.get(rowkey, []) if rowkey else []
        count += len(rows)
        done = not paging
        if paging == 'offset':
            done = len(rows) == 0  # require explicit empty terminal page, even after a short page
            params['offset'] += len(rows)
        elif paging:
            if paging not in payload:
                raise RuntimeError(f'Missing pagination cursor in {run}')
            cursor = payload[paging]
            done = cursor in ('', None, 'LTE=')
            if not done:
                if cursor in seen_cursors:
                    raise RuntimeError('Repeated pagination cursor')
                seen_cursors.add(cursor)
                params[paging] = cursor
        print(json.dumps({'source': args.source, 'page': number, 'rows': len(rows),
                          'complete': done, 'archive': str(run)}), flush=True)
        if done:
            with (run / 'manifest.json').open('x') as output:
                json.dump({'source': args.source, 'pages': number + 1, 'rows': count,
                           'pagination_complete': True, 'finished_utc': time.time()}, output, indent=2)
            return
    raise RuntimeError('Safety page bound reached: incomplete archive')


if __name__ == '__main__':
    main()
