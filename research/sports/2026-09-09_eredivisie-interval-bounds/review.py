#!/usr/bin/env python3
"""Fail-closed official exception review. This cannot register evidence by itself."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
AMSTERDAM = ZoneInfo('Europe/Amsterdam')
OFFICIAL_DOMAINS = {'www.knvb.nl', 'eredivisie.nl', 'english.ajax.nl', 'www.az.nl',
                    'www.nac.nl', 'www.sparta-rotterdam.nl', 'excelsiorrotterdam.nl',
                    'd3et0fncpz2hhr.cloudfront.net'}


def review_result(result: dict, review: dict, manifest: dict) -> dict:
    if (result['failures'] or result['original_fixtures'] != 306
            or result['final_regular_season_fixtures'] != 306 or result['final_whistles'] != 306):
        raise ValueError('Incomplete population/completion gate')
    rows = result['rows']
    exceptions = {r['event_id']: r for r in rows if r['review_required'] or r.get('initial_review_required')}
    events = review['events']
    if set(events) != set(exceptions):
        raise ValueError('Require exactly the full exception review')
    for event_id, row in exceptions.items():
        reviewed = events[event_id]
        if (reviewed['home'], reviewed['away']) != (row['home'], row['away']):
            raise ValueError('Official review competitor mismatch')
        original_date = datetime.fromisoformat(row['original_lower_bound']).date().isoformat()
        started = datetime.fromisoformat(row['actual_start']).astimezone(AMSTERDAM)
        finished = datetime.fromisoformat(row['actual_completion']).astimezone(AMSTERDAM)
        if (reviewed['original_lower_date'] != original_date
                or reviewed['final_date_local'] != started.date().isoformat()):
            raise ValueError('Official review date mismatch')
        if reviewed['kind'] not in {'schedule_change', 'schedule_advance', 'explicit_original_alternative', 'completed_suspension'}:
            raise ValueError('Unknown exception disposition')
        # A changed resume kickoff alone does not prove a suspended match finished.
        # Both specifically identified suspensions and any clock-spanning completion
        # need the actual completion date confirmed by an official result report.
        if (reviewed['kind'] == 'completed_suspension' or finished.date() != started.date()):
            if reviewed.get('completion_date_local') != finished.date().isoformat():
                raise ValueError('Official completion date required for suspension')
        if not reviewed['sources'] or not reviewed['note']:
            raise ValueError('Missing official source review')
        for source in reviewed['sources']:
            entry = manifest['sources'].get(source)
            if (not entry or entry['status'] != 200
                    or urlsplit(entry['url']).hostname not in OFFICIAL_DOMAINS):
                raise ValueError('Missing/failed/nonofficial review source')
    output = deepcopy(result)
    output['official_review_passed'] = True
    output['verdict'] = 'BLOCKED_PENDING_INDEPENDENT_REPLAY'
    # No evidence keys or independent-review claim are minted by this function.
    output['registered_rates'] = {}
    return output


if __name__ == '__main__':
    import argparse
    import measure
    import manifest
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corrected', action='store_true')
    args = parser.parse_args()
    pinned = json.loads((HERE / 'source_manifest.json').read_text())
    manifest.verify(pinned)
    result = measure.measure(corrected=args.corrected)
    result_name = 'results_corrected.json' if args.corrected else 'results.json'
    if result != json.loads((HERE / result_name).read_text()):
        raise ValueError('Offline measurement changed from preserved first result')
    review_name = 'official_review_corrected.json' if args.corrected else 'official_review.json'
    reviewed = review_result(result, json.loads((HERE / review_name).read_text()), pinned)
    print(json.dumps({key: value for key, value in reviewed.items() if key != 'rows'}, indent=2, sort_keys=True))
