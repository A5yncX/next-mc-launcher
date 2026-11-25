"""Verify loose-item pressing, split stacks, and restart without a second strike."""
import argparse
import asyncio
from collections import Counter
from pathlib import Path
import socket
import tempfile

from generate_full_registry import create_ids
from generate_pumpkin_data import CLIENT, read_json
from smoke_core import CONFIG, DATA, HERE, server, until
from smoke_drivetrain import watch
from smoke_placement import coords, eventually
from smoke_press import GAP, IRON, MOTOR, PRESS, SHEET


async def items(call):
    found = Counter()
    for entity in (await call('entities 12 minecraft:item'))['entities']:
        stack = entity['item']
        found[stack['item']] += stack['count']
    return found


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    ids = create_ids(read_json(CLIENT / 'registries.json'), 'block_entity_type')
    state = 'create:mechanical_press[facing=east]'
    targets = {PRESS: (state, ids['create:mechanical_press'])}
    x, y, z = GAP

    async def assert_totals(call, expected):
        for _ in range(60):
            observed = await items(call)
            if observed == expected:
                return
            await asyncio.sleep(.2)
        raise AssertionError((observed, expected))

    async with server(args, room, port, 'press-world') as (send, _):
        async with watch(args, room, port, 'Builder', targets) as (a, first), \
                watch(args, room, port, 'Witness', targets) as (b, second):
            await asyncio.sleep(2)
            send('fill -272 78 -112 -261 82 -103 air', 'fill -272 78 -112 -261 78 -103 stone',
                 f'setblock {coords(PRESS)} {state}',
                 f'summon minecraft:item {x + .5} {y + .3} {z + .5} {{Item:{{id:"{IRON}",count:2}},PickupDelay:32767s}}')
            for name, call, from_x in [('Builder', a, -271.5), ('Witness', b, -264.5)]:
                point = (from_x, 79, -106.5)
                send(f'tp {name} {coords(point)}')
                await eventually(lambda: call('state'), lambda r: r.get('player') and all(
                    abs(actual - expected) < .2 for actual, expected in zip(r['player']['position'], point)), f'{name} in reach')
                await assert_totals(call, Counter({IRON: 2}))
            assert all(o.tags[PRESS]['Running'] == 0 for o in (first, second))
            send(f'setblock {coords(MOTOR)} create:creative_motor[facing=east]')
            await until(lambda: all(o.tags.get(PRESS, {}).get('Running') == 1 and o.tags[PRESS]['Mode'] == 0
                                    for o in (first, second)), 'both clients see world-mode press start')
            await until(lambda: all(o.tags.get(PRESS, {}).get('Applied') == 1 for o in (first, second)),
                        'both clients see first strike')
            send(f'setblock {coords(MOTOR)} air')
            await assert_totals(a, Counter({IRON: 1, SHEET: 1}))
            await assert_totals(b, Counter({IRON: 1, SHEET: 1}))

    reconnect = room / 'reconnect'
    reconnect.mkdir()
    async with server(args, room, port, 'restart') as (_, __):
        async with watch(args, reconnect, port, 'Builder', targets) as (call, o):
            assert o.tags[PRESS]['Mode'] == 0 and o.tags[PRESS]['Applied'] == 1
            await assert_totals(call, Counter({IRON: 1, SHEET: 1}))
            print('PASS: two clients, exactly one loose item pressed, both items persisted after restart')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', type=Path, default=DATA / 'components/create-atlas-beta.1/target/plain/release/horizon-client.exe')
    parser.add_argument('--pumpkin', type=Path, default=HERE.parent / '.cache/core-target/debug/pumpkin.exe')
    parser.add_argument('--resources', type=Path, default=DATA / 'resources-create-v4')
    parser.add_argument('--create-jar', type=Path)
    args = parser.parse_args()
    for attr, path in vars(args).items():
        if path is not None:
            setattr(args, attr, path.resolve(strict=True))
    room = Path(tempfile.mkdtemp(prefix='create-press-world-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
