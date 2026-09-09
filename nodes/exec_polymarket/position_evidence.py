"""Same-read position evidence for narrow terminal-zero incident resolution.

Never filters physical Position quantities. Redeemable is a venue assertion, not
an on-chain payout proof. No price mark alone can make a live token terminal.
"""
from dataclasses import asdict
from decimal import Decimal
import hashlib
import json
import re

ENDPOINT = 'https://data-api.polymarket.com/positions'
PAGE_LIMIT = 500
MAX_OFFSET = 10000
MAX_AGE_S = 60


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False,
                      default=lambda x: str(x) if isinstance(x, Decimal) else _unsupported(x))


def _unsupported(value):
    raise TypeError(f'unsupported source type: {type(value).__name__}')


def sha(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def number(value):
    if value is None or isinstance(value, bool):
        raise ValueError('missing/boolean position amount')
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError('nonfinite position amount')
    return result


def capture(rows, paging, *, observed_utc):
    """Freeze the full parsed JSON batch. Hash is not a raw HTTP-byte hash."""
    if not isinstance(rows, list) or not isinstance(paging, dict):
        raise ValueError('missing complete position read metadata')
    source = json.loads(canonical(dict(endpoint=ENDPOINT, observed_utc=observed_utc, paging=paging, rows=rows)))
    evidence = dict(source=source, source_sha256=sha(source))
    validate_source(evidence)
    return evidence


def validate_source(evidence):
    if not isinstance(evidence, dict) or set(evidence) != {'source', 'source_sha256'}:
        raise ValueError('missing exact position source envelope')
    source = evidence['source']
    if (not isinstance(source, dict) or set(source) != {'endpoint', 'observed_utc', 'paging', 'rows'}
            or source['endpoint'] != ENDPOINT or sha(source) != evidence['source_sha256']):
        raise ValueError('position source hash/identity mismatch')
    if number(source['observed_utc']) <= 0:
        raise ValueError('invalid position observation time')
    paging, rows = source['paging'], source['rows']
    if (not isinstance(paging, dict) or set(paging) != {'user', 'sizeThreshold', 'limit', 'pages', 'complete'}
            or paging['complete'] is not True or type(paging['limit']) is not int or paging['limit'] != PAGE_LIMIT
            or type(paging['sizeThreshold']) is not int or paging['sizeThreshold'] != 0
            or not isinstance(paging['user'], str) or not re.fullmatch(r'0x[0-9a-fA-F]{40}', paging['user'])
            or not isinstance(rows, list) or not isinstance(paging['pages'], list) or not paging['pages']):
        raise ValueError('incomplete or unsupported position pagination')
    cursor = 0
    for index, page in enumerate(paging['pages']):
        if not isinstance(page, dict) or set(page) != {'offset', 'count', 'sha256'}:
            raise ValueError('invalid position page evidence')
        count, offset = page['count'], page['offset']
        if (type(count) is not int or not 0 <= count <= PAGE_LIMIT or type(offset) is not int
                or offset != cursor or offset > MAX_OFFSET or sha(rows[cursor:cursor + count]) != page['sha256']
                or (index < len(paging['pages']) - 1 and count != PAGE_LIMIT)):
            raise ValueError('position page coverage mismatch')
        cursor += count
    if cursor != len(rows) or paging['pages'][-1]['count'] >= PAGE_LIMIT:
        raise ValueError('terminal short page missing or extra raw rows')
    return source


def terminal_zero_positions(positions, evidence, *, pass_started_utc, now):
    """Return full auditable proof only; never remove/zero any Position record."""
    source = validate_source(evidence)
    observed = number(source['observed_utc'])
    if not number(pass_started_utc) <= observed <= number(now) or number(now) - observed > MAX_AGE_S:
        raise ValueError('position evidence is not fresh from this guard pass')
    if positions is None:
        raise ValueError('unknown physical positions')
    physical = {}
    for position in positions:
        if (position.venue != 'polymarket' or position.side != 'yes' or position.market_id in physical
                or number(position.contracts) <= 0 or number(position.fetched_utc) != observed):
            raise ValueError('invalid or stale physical position projection')
        physical[position.market_id] = number(position.contracts)
    positive, seen, remnants = {}, set(), []
    for row in source['rows']:
        if not isinstance(row, dict):
            raise ValueError('malformed position row')
        asset, wallet, condition = row.get('asset'), row.get('proxyWallet'), row.get('conditionId')
        if (not isinstance(asset, str) or not asset or asset in seen
                or not isinstance(wallet, str) or wallet.lower() != source['paging']['user'].lower()
                or not isinstance(condition, str) or not re.fullmatch(r'0x[0-9a-fA-F]{64}', condition)):
            raise ValueError('duplicate/unbound position token, wallet or condition')
        seen.add(asset)
        size, value, price = number(row.get('size')), number(row.get('currentValue')), number(row.get('curPrice'))
        if size < 0 or value != 0 or not 0 <= price <= 1:
            raise ValueError('position has value, negative size or malformed price')
        if row.get('avgPrice') is not None and not 0 <= number(row['avgPrice']) <= 1:
            raise ValueError('malformed historical position price')
        if size == 0:
            continue
        positive[asset] = size
        if row.get('redeemable') is not True or price != 0:
            raise ValueError('positive token is not venue-proved redeemable zero-value')
        for key in ('resolved', 'closed'):
            if key in row and row[key] is not True:
                raise ValueError('contradictory terminal position status')
        for key in ('active', 'acceptingOrders', 'trading', 'mergeable'):
            if key in row and row[key] is not False:
                raise ValueError('contradictory active/mergeable position status')
        if 'umaResolutionStatus' in row and row['umaResolutionStatus'] != 'resolved':
            raise ValueError('contradictory resolution status')
        remnants.append(dict(asset=asset, conditionId=condition, size=str(size), row_sha256=sha(row)))
    if positive != physical:
        raise ValueError('raw source and physical position quantities differ')
    return dict(evidence=evidence, positions=[asdict(p) for p in positions], remnants=remnants,
                interpretation='venue-asserted redeemable terminal zero; physical quantities preserved; no cash/PnL inference')
