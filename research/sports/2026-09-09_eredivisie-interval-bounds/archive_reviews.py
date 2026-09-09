#!/usr/bin/env python3
"""Append-only acquisition of the official sources read for L50 exceptions."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
module_spec = importlib.util.spec_from_file_location(
    'l49_archive', HERE.parent / '2026-09-09_eredivisie-original-schedule/archive_source.py')
archive_module = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(archive_module)
archive_module.ROOT = Path('/Volumes/Kilos/janus/research/eredivisie-L50')

SOURCES = {
    'ajax-completion': 'https://english.ajax.nl/articles/ajax-record-home-win-over-fc-groningen-in-empty-johan-cruyff-arena/',
    'ajax-resumption': 'https://www.knvb.nl/node/71273',
    'az-results': 'https://www.az.nl/wedstrijden/az',
    'nac-completion': 'https://www.nac.nl/nieuws/winst-in-twee-delen-voor-gedegradeerd-nac',
    'nec-january-reschedule': 'https://www.knvb.nl/nieuws/betaald-voetbal/vriendenloterij-eredivisie/71403/nieuwe-data-voor-afgelaste-wedstrijden',
    'march-reschedule': 'https://www.knvb.nl/node/71450',
    'sparta-completion': 'https://www.sparta-rotterdam.nl/sparta-en-n-e-c-houden-elkaar-in-evenwicht/',
    'sparta-suspension': 'https://www.sparta-rotterdam.nl/sparta-n-e-c-definitief-gestaakt/',
    'excelsior-reschedule': 'https://excelsiorrotterdam.nl/2025/12/schema2026/',
    'december-reschedule': 'https://www.knvb.nl/nieuws/betaald-voetbal/competitiezaken/71225/wedstrijdwijzigingen-speelronde-17-vriendenloterij',
}

if __name__ == '__main__':
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(archive_module.archive, url, label) for label, url in SOURCES.items()]
        for future in futures:
            print(json.dumps(future.result(), sort_keys=True), flush=True)
