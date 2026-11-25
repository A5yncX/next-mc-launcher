"""Verify a large wheel's multiblock, water drive, restart and single drop."""
import argparse
import asyncio
from pathlib import Path
import socket
import tempfile

from generate_full_registry import create_ids
from generate_pumpkin_data import CLIENT, read_json
from smoke_core import CONFIG, DATA, HERE, ROOT, server, until
from smoke_drivetrain import watch
from smoke_placement import aim, coords, eventually, state_on
from smoke_registry import inventory_has

WHEEL = (-268, 79, -108)
SHAFT = (-267, 79, -108)
WHEEL_ITEM = 'create:large_water_wheel'
WHEEL_STATE = WHEEL_ITEM + '[axis=x,extension=false]'
SHAFT_STATE = 'create:shaft[axis=x,waterlogged=false]'
PART = 'create:water_wheel_structure'
RING = tuple((WHEEL[0], WHEEL[1] + dy, WHEEL[2] + dz)
             for dy in (-1, 0, 1) for dz in (-1, 0, 1) if dy or dz)
OBSTRUCTION = (-268, 80, -108)
CURRENT = (-268, 79, -106)


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    ids = create_ids(read_json(CLIENT / 'registries.json'), 'block_entity_type')
    targets = {pos: (state, ids[state.split('[')[0]]) for pos, state in ((WHEEL, WHEEL_STATE), (SHAFT, SHAFT_STATE))}

    async def ring(call, name):
        for p in RING:
            await eventually(lambda: call(f'block {coords(p)}'), lambda row: row['block'] == name,
                             f'{coords(p)}: {name}')

    def running(observer):
        wheel, shaft = (observer.tags.get(p, {}) for p in (WHEEL, SHAFT))
        return (wheel.get('Speed'), shaft.get('Speed'), wheel.get('FlowScore'),
                wheel.get('create_horizon.StructureReady')) == (4, 4, 1, 1)

    async with server(args, room, port, 'large-water') as (send, _):
        async with watch(args, room, port, 'Builder', targets) as (build, one), \
                watch(args, room, port, 'Witness', targets) as (see, two):
            send('fill -272 77 -112 -261 77 -102 stone', 'fill -272 78 -112 -261 82 -102 air',
                 f'setblock {coords(SHAFT)} {SHAFT_STATE}', f'setblock {coords(OBSTRUCTION)} stone',
                 'tp Builder -270.5 78 -107.5', f'give Builder {WHEEL_ITEM} 1')
            await eventually(lambda: build('state'), lambda row: abs(row['player']['position'][0] + 270.5) < .1,
                             'Builder in placement range')
            await state_on(see, OBSTRUCTION, 'minecraft:stone')
            await state_on(build, SHAFT, SHAFT_STATE)
            await eventually(lambda: build('inventory'), lambda row: inventory_has(row, WHEEL_ITEM), 'large wheel in inventory')
            await build(f'select {WHEEL_ITEM}')
            await aim(build, (-266.99, 79.5, -107.5), SHAFT)
            await build('use-item')
            await asyncio.sleep(1)
            await state_on(see, WHEEL, 'minecraft:air')
            await state_on(see, OBSTRUCTION, 'minecraft:stone')
            print('PASS: blocked placement leaves existing block untouched', flush=True)
            send(f'setblock {coords(OBSTRUCTION)} air')
            await state_on(build, OBSTRUCTION, 'minecraft:air')
            await build('use-item')
            await asyncio.gather(*(state_on(call, WHEEL, WHEEL_STATE) for call in (build, see)))
            await asyncio.gather(ring(build, PART), ring(see, PART))
            x, y, z = CURRENT
            send(f'setblock {x-1} {y} {z} stone', f'setblock {x+1} {y} {z} stone',
                 f'setblock {x} {y} {z+1} stone', f'setblock {x} {y+1} {z} stone',
                 f'setblock {x} {y-1} {z} magma_block', f'setblock {x} {y} {z} water')
            await state_on(build, CURRENT, 'minecraft:bubble_column[drag=true]')
            await until(lambda: running(one) and running(two), 'both clients: eight parts and +4 RPM at the shaft', 25)

    reconnect = room / 'reconnect'
    reconnect.mkdir()
    async with server(args, room, port, 'restart') as (send, _):
        async with watch(args, reconnect, port, 'Builder', targets) as (again, observer):
            await ring(again, PART)
            await until(lambda: running(observer), 'restart kept all parts and wheel speed', 25)
            send(f'setblock {coords(OBSTRUCTION)} air')
            await state_on(again, WHEEL, 'minecraft:air')
            await ring(again, 'minecraft:air')
            await eventually(lambda: again('entities 8 minecraft:item'), lambda row: [
                item['item']['count'] for item in row['entities'] if item['item']['item'] == WHEEL_ITEM
            ] == [1], 'only one large wheel dropped')
            await until(lambda: observer.tags.get(SHAFT, {}).get('Speed') == 0, 'breaking one part clears the ring, makes one drop and stops the shaft')


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
    room = Path(tempfile.mkdtemp(prefix='create-large-water-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
