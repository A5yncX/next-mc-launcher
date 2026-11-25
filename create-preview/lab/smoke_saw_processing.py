"""Two real clients: saw intake, powered cutting, blocked output, and reload."""
import argparse
import asyncio
from pathlib import Path
import socket
import tempfile

from generate_full_registry import create_ids
from generate_pumpkin_data import CLIENT, read_json
from smoke_core import CONFIG, DATA, HERE, ROOT, server, until
from smoke_drivetrain import watch
from smoke_placement import coords, eventually, state_on

SAW = 'create:mechanical_saw'
POS, SOURCE, BLOCKER = (-268, 78, -108), (-269, 78, -108), (-268, 78, -109)
INPUT, OUTPUT = 'create:andesite_alloy', 'create:shaft'


def contents(observer):
    inv = observer.tags.get(POS, {}).get('Inventory', {})
    return [(row['id'], row['count']) for row in inv.get('Items', [])]


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    targets = {POS: (SAW, create_ids(read_json(CLIENT / 'registries.json'), 'block_entity_type')[SAW])}

    async with server(args, room, port, 'saw-processing') as (send, _):
        async with watch(args, room, port, 'Builder', targets) as (build, a), \
                watch(args, room, port, 'Witness', targets) as (see, b):
            await asyncio.sleep(2)
            send('fill -273 77 -112 -260 77 -103 stone', 'fill -273 78 -112 -260 82 -103 air')
            await asyncio.sleep(1)
            saw = f'{SAW}[axis_along_first=true,facing=up,flipped=false]'
            send(f'setblock {coords(POS)} {saw}', f'setblock {coords(BLOCKER)} stone')
            await state_on(see, POS, saw)
            await state_on(see, BLOCKER, 'minecraft:stone')
            send(f'summon minecraft:item -267.5 79.5 -107.5 {{Item:{{id:"{INPUT}",count:1}},PickupDelay:32767s}}')
            await eventually(lambda: build('entities 12 minecraft:item'), lambda row: any(
                x['item']['item'] == INPUT for x in row['entities']), 'unpowered saw leaves the input item outside')
            assert contents(a) == contents(b) == []
            send(f'setblock {coords(SOURCE)} create:creative_motor[facing=east]')
            await until(lambda: all(o.tags.get(POS, {}).get('Speed') == 32 for o in (a, b)), 'saw at +32 RPM')
            await until(lambda: all(contents(o) == [(INPUT, 1)] for o in (a, b)), 'both clients see input accepted')
            await until(lambda: all(contents(o) == [(OUTPUT, 6)] for o in (a, b)),
                        'one andesite alloy cut into six shafts, held by the blocked output', 35)

    reconnect = room / 'reconnect'
    reconnect.mkdir()
    async with server(args, room, port, 'restart') as (send, _):
        async with watch(args, reconnect, port, 'Builder', targets) as (build, observer):
            await until(lambda: contents(observer) == [(OUTPUT, 6)], 'blocked output survived reload')
            send(f'setblock {coords(BLOCKER)} air')
            await eventually(lambda: build('entities 12 minecraft:item'), lambda row: sum(
                x['item']['count'] for x in row['entities'] if x['item']['item'] == OUTPUT
            ) == 6, 'exactly six shafts ejected as items')
            await until(lambda: contents(observer) == [], 'saw inventory empty after ejection')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', type=Path, default=ROOT / 'research_create_rust/.create-lab-build/game-target/fast/horizon-client.exe')
    parser.add_argument('--pumpkin', type=Path, default=HERE.parent / '.cache/core-target/debug/pumpkin.exe')
    parser.add_argument('--resources', type=Path, default=DATA / 'resources-create-v4')
    parser.add_argument('--create-jar', type=Path)
    args = parser.parse_args()
    for attr in ('client', 'pumpkin', 'resources', 'create_jar'):
        if path := getattr(args, attr):
            setattr(args, attr, path.resolve(strict=True))
    room = Path(tempfile.mkdtemp(prefix='create-saw-processing-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
