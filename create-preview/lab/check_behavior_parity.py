"""Check that the Markdown acceptance ledger covers the exact pinned Create registry."""
import argparse
from collections import Counter
from pathlib import Path
import re

from generate_full_registry import create_ids
from generate_pumpkin_data import CLIENT, read_json

LEDGER = Path(__file__).with_name('behavior-parity.md')


def check(ledger, client):
    text = ledger.read_text(encoding='utf-8')
    expected = {name.removeprefix('create:') for name in create_ids(read_json(client / 'registries.json'), 'block')}
    _, marker, section = text.partition('## Per-block ledger\n')
    if not marker or len(expected) != 106:
        raise ValueError('Missing ledger section or wrong pinned registry')
    statuses = Counter({'Complete': 0, 'Partial': 0, 'Registry only': 0})
    seen = set()
    for names, status, evidence in re.findall(r'^\| ([a-z_][\w, ]*) \| ([\w ]+) \| (.+?) \|$', section, re.M):
        if status not in statuses or not evidence.strip():
            raise ValueError(f'Unknown status or missing evidence: {names}')
        for name in names.split(', '):
            if name in seen or name not in expected:
                raise ValueError(f'Duplicate or unregistered block in ledger: {name}')
            seen.add(name)
            statuses[status] += 1
    if missing := expected - seen:
        raise ValueError(f'Missing blocks: {", ".join(sorted(missing))}')
    if f'{statuses["Complete"]}/{len(expected)} fully accepted' not in text:
        raise ValueError('The summary does not match the ledger')
    return statuses


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', type=Path, default=CLIENT, help='pinned Horizon registry export directory')
    parser.add_argument('--require-complete', action='store_true', help='reject an unfinished port')
    args = parser.parse_args()
    try:
        statuses = check(LEDGER, args.client)
    except (KeyError, OSError, ValueError) as exc:
        parser.exit(1, f'{exc}\n')
    print(', '.join(f'{state}: {count}' for state, count in statuses.items()))
    if args.require_complete and (statuses['Partial'] or statuses['Registry only']):
        parser.exit(1, 'Do not publish: acceptance is incomplete.\n')
