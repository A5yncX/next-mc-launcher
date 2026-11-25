"""Real Horizon clients feed the pinned 5×5 mechanical-crafting layout."""
import argparse
import asyncio
import json
from pathlib import Path
import socket
import tempfile

from generate_full_registry import CONTENT_JSON, create_ids
from generate_pumpkin_data import CLIENT, read_json
from smoke_core import CONFIG, DATA, HERE, ROOT, server, until
from smoke_depot import inventory_is
from smoke_drivetrain import watch
from smoke_encasing import move
from smoke_placement import aim, coords, state_on

CRAFTER = 'create:mechanical_crafter'
RESULT = 'create:crushing_wheel'
CENTER = (-267, 78, -108)
OUTPUT = (-267, 77, -108)
COG, MOTOR = (-269, 78, -108), (-269, 78, -109)
INGREDIENTS = {'A': 'create:andesite_alloy', 'P': 'minecraft:oak_planks', 'S': 'minecraft:stone'}


def cells():
    data = read_json(CONTENT_JSON)
    recipe = json.loads(data['data/create/recipe/mechanical_crafting/crushing_wheel.json'])
    slots = {(CENTER[0] + x - 2, CENTER[1] + 4 - y, CENTER[2]): INGREDIENTS[c]
             for y, row in enumerate(recipe['pattern']) for x, c in enumerate(row) if c != ' '}
    for p, ingredient in slots.items():
        x, y, z = p
        pointing = 'down' if (x, y - 1, z) in slots or p == CENTER else 'right' if x < CENTER[0] else 'left'
        yield p, f'{CRAFTER}[facing=south,pointing={pointing}]', ingredient


def phase(o, p=CENTER):
    return o.tags.get(p, {}).get('Phase')


def result(o):
    return sum(row.get('item', {}).get('count', 0)
               for row in o.tags.get(CENTER, {}).get('GroupedItems', {}).get('Grid', [])
               if row.get('item', {}).get('id') == RESULT)


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    ids = create_ids(read_json(CLIENT / 'registries.json'), 'block_entity_type')
    placements = list(cells())
    targets = {p: (state, ids[CRAFTER]) for p, state, _ in placements}
    assert len(targets) == 21

    async with server(args, room, port, 'crafter') as (send, _):
        async with watch(args, room, port, 'Builder', targets) as (build, a), \
                watch(args, room, port, 'Witness', targets) as (see, b):
            await asyncio.sleep(2)
            send('fill -273 77 -112 -261 77 -102 stone', 'fill -273 78 -112 -261 85 -102 air')
            await asyncio.sleep(1)
            send(*(f'setblock {coords(p)} {state}' for p, state, _ in placements),
                 f'setblock {coords(COG)} create:cogwheel[axis=z,waterlogged=false]',
                 'gamemode survival Builder',
                 *(f'item replace entity Builder hotbar.{slot} with {name} 32'
                   for slot, name in enumerate(INGREDIENTS.values())))
            for p, state, _ in placements:
                await state_on(see, p, state)
            await move(build, send, (-267.5, 78, -104.5))
            for name in INGREDIENTS.values():
                await inventory_is(build, name, 32)
            for p, _, name in placements:
                x, y, z = p
                await build(f'select {name}')
                await aim(build, (x + .5, y + .5, z + .99), p)
                await build('use-item')
                await until(lambda: all(o.tags.get(p, {}).get('Inventory', {}).get('Items', [{}])[0].get('id') == name
                                        if o.tags.get(p, {}).get('Inventory', {}).get('Items') else False for o in (a, b)),
                            f'both clients see {name} in {p}', 8)
            await inventory_is(build, INGREDIENTS['A'], 16)
            await inventory_is(build, INGREDIENTS['P'], 28)
            await inventory_is(build, INGREDIENTS['S'], 31)
            assert phase(a) == phase(b) == 'IDLE'
            send(f'setblock {coords(MOTOR)} create:creative_motor[facing=south]')
            await until(lambda: all(abs(o.tags.get(p, {}).get('Speed', 0)) == 32
                                    for o in (a,b) for p in targets), 'all 21 crafters connected at 32 RPM')
            assert phase(a) == phase(b) == 'IDLE', 'blocked outlet must prevent starting'
            send(f'setblock {coords(OUTPUT)} air')
            await until(lambda: all(phase(o) in ('ACCEPTING','ASSEMBLING','CRAFTING') for o in (a,b)), 'both clients see active chain')
            send(f'setblock {coords(OUTPUT)} stone')
            await until(lambda: all(phase(o) == 'INSERTING' and result(o) == 2 for o in (a,b)),
                        'two exact wheels retained by blocked output', 60)

    reconnect = room / 'reconnect'
    reconnect.mkdir()
    async with server(args, room, port, 'restart') as (send, _):
        async with watch(args, reconnect, port, 'Builder', targets) as (build, o):
            await until(lambda: phase(o) == 'INSERTING' and result(o) == 2, 'blocked result survived restart')
            send(f'setblock {coords(OUTPUT)} air')
            await until(lambda: all(phase(o,p) == 'IDLE' for p in targets), 'all 21 crafters reset without retained stacks')
            await move(build, send, (-267.5, 78, -104.5))
            async def check_items():
                entities = (await build('entities 12 minecraft:item'))['entities']
                return sum(x['item']['count'] for x in entities if x['item']['item'] == RESULT) == 2
            for _ in range(30):
                if await check_items():
                    break
                await asyncio.sleep(.2)
            else:
                raise AssertionError('expected exactly two ejected wheels')
            print('PASS: 21 real hand insertions, blocked mechanical recipe, reload, exactly two wheels')


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
    room = Path(tempfile.mkdtemp(prefix='create-crafter-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
