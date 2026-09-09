"""L58 public source freeze; exclusive files, raw bytes and request provenance."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import re
from pathlib import Path
from urllib.request import Request, urlopen

DATA = Path('/Volumes/Kilos/janus/research/ucl-settlement-bounds')
SOURCES = {
    'original-2024-pot.pdf': 'https://editorial.uefa.com/resources/0290-1bbe0f238404-c5dbaf60ad4d-1000/uefa_champions_league_2024-25_league_phase_draw_results_calendar_by_pot.pdf',
    'original-2024-date.pdf': 'https://editorial.uefa.com/resources/0290-1bbe1fa4ba2d-246d366b8d50-1000/uefa_champions_league_2024-25_league_phase_draw_results_calendar_by_date_20240831133635.pdf',
    'uefa-draw-publication.html': 'https://www.uefa.com/uefachampionsleague/news/028e-1b1125f199a1-ace85e395aa8-1000/',
    'uefa-calendar-publication.html': 'https://www.uefa.com/uefachampionsleague/news/0290-1bbaa109447c-6dbed8c6fe14-1000--champions-league-league-phase-draw-all-36-teams-learn-their/',
    'uefa-results.html': 'https://www.uefa.com/uefachampionsleague/news/0290-1bbe6365b47a-0668db2bbcb1-1000--champions-league-all-the-fixtures-and-results/',
    'espn-scoreboard.json': 'https://site.web.api.espn.com/apis/site/v2/sports/soccer/uefa.champions/scoreboard?dates=20240901-20250201&limit=1000',
}


def freeze(item):
    name, url = item
    DATA.mkdir(parents=True, exist_ok=True)
    path = DATA / name
    if path.exists():
        metadata = json.loads(path.with_suffix(path.suffix + '.meta.json').read_text())
        assert hashlib.sha256(path.read_bytes()).hexdigest() == metadata['sha256']
        assert metadata['url'] == url
        return metadata
    with urlopen(Request(url, headers={'User-Agent': 'Janus registered historical research'}), timeout=45) as response:
        raw = response.read()
        metadata = {'url': url, 'retrieved_at': datetime.now(timezone.utc).isoformat(),
                    'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw),
                    'headers': dict(response.headers), 'status': response.status, 'path': str(path)}
    with path.open('xb') as out:
        out.write(raw)
    with path.with_suffix(path.suffix + '.meta.json').open('x') as out:
        json.dump(metadata, out, indent=2)
    return metadata


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--summaries', action='store_true')
    parser.add_argument('--uefa-reports', action='store_true')
    args = parser.parse_args()
    sources = SOURCES
    if args.summaries:
        scoreboard = json.loads((DATA / 'espn-scoreboard.json').read_text())
        sources = {f"summary-{e['id']}.json": 'https://site.web.api.espn.com/apis/site/v2/sports/soccer/uefa.champions/summary?event=' + e['id']
                   for e in scoreboard['events']}
    if args.uefa_reports:
        text = (DATA / 'uefa-results.html').read_text()
        section = text.split('League phase </h2>', 1)[1].split('</article>', 1)[0]
        ids = re.findall(r'/match/(\d+)', section)
        if len(ids) != 144 or len(set(ids)) != 144:
            raise ValueError(f'League phase needs 144 unique reports, got {len(ids)}')
        sources = {f'uefa-report-{i}.pdf': f'https://www.uefa.com/newsfiles/UCL/2025/{i}_FR.pdf' for i in ids}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for result in pool.map(freeze, sources.items()):
            print(result['path'], result['sha256'])
