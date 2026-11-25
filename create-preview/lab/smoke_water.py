"""Check small water wheel placement, real currents, material and restart on two clients."""
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

WHEEL = (-268, 78, -108)
SHAFT = (-267, 78, -108)
WHEEL_STATE = 'create:water_wheel[facing=west]'
SHAFT_STATE = 'create:shaft[axis=x,waterlogged=false]'
SOUTH = (-268, 78, -107)
NORTH = (-268, 78, -109)


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    ids = create_ids(read_json(CLIENT / 'registries.json'), 'block_entity_type')
    targets = {pos: (state, ids[state.split('[')[0]]) for pos, state in ((WHEEL, WHEEL_STATE), (SHAFT, SHAFT_STATE))}

    async def measure(observers, rpm, score, wood, label):
        def correct(observer):
            wheel, shaft = (observer.tags.get(p, {}) for p in (WHEEL, SHAFT))
            return (wheel.get('Speed'), shaft.get('Speed'), wheel.get('FlowScore'), wheel.get('Material')) == (
                rpm, rpm, score, {'Name': f'minecraft:{wood}_planks'})
        try:
            await until(lambda: all(map(correct, observers)), label, 30)
        except TimeoutError as exc:
            raise AssertionError((label, [observer.tags for observer in observers])) from exc

    async with server(args, room, port, 'water') as (send, _):
        async with watch(args, room, port, 'Builder', targets) as (build, one), \
                watch(args, room, port, 'Witness', targets) as (see, two):
            send('fill -272 77 -112 -261 77 -102 stone', 'fill -272 78 -112 -261 81 -102 air',
                 f'setblock {coords(SHAFT)} {SHAFT_STATE}', 'tp Builder -270.5 78 -107.5',
                 'give Builder create:water_wheel 2', 'give Builder minecraft:cherry_planks 1')
            await eventually(lambda: build('state'), lambda row: abs(row['player']['position'][0] + 270.5) < .1,
                             'Builder in placement range')
            await state_on(build, SHAFT, SHAFT_STATE)
            await eventually(lambda: build('inventory'), lambda row: inventory_has(row, 'create:water_wheel'), 'wheel in inventory')
            await build('select create:water_wheel')
            await aim(build, (-267.001, 78.5, -107.5), SHAFT)
            await build('use-item')
            await asyncio.gather(state_on(build, WHEEL, WHEEL_STATE), state_on(see, WHEEL, WHEEL_STATE))
            await measure((one, two), 0, 0, 'spruce', 'placed wheel idles without water')
            await build('select minecraft:cherry_planks')
            await aim(build, (-267.5, 78.5, -107.5), WHEEL)
            await build('use-item')
            await measure((one, two), 0, 0, 'cherry', 'right-click recolored wheel for both clients')

            async def magma(pos):
                x, y, z = pos
                outer = z + (1 if z > WHEEL[2] else -1)
                send(f'setblock {x-1} {y} {z} stone', f'setblock {x+1} {y} {z} stone',
                     f'setblock {x} {y} {outer} stone', f'setblock {x} {y+1} {z} stone',
                     f'setblock {x} {y-1} {z} minecraft:magma_block', f'setblock {coords(pos)} minecraft:water')
                await state_on(build, pos, 'minecraft:bubble_column[drag=true]')

            await magma(SOUTH)
            await measure((one, two), 8, 1, 'cherry', 'actual south bubble column drives wheel and shaft at +8 RPM')
            await magma(NORTH)
            await measure((one, two), 0, 0, 'cherry', 'opposing currents cancel')
            send(f'setblock {coords(SOUTH)} air')
            await measure((one, two), -8, -1, 'cherry', 'north current reverses the wheel and shaft')

    reconnect = room / 'reconnect'
    reconnect.mkdir()
    async with server(args, room, port, 'restart') as (_, __):
        async with watch(args, reconnect, port, 'Builder', targets) as (again, observer):
            await state_on(again, WHEEL, WHEEL_STATE)
            await state_on(again, NORTH, 'minecraft:bubble_column[drag=true]')
            await measure((observer,), -8, -1, 'cherry', 'restart recovered flow, signed speed and material')


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
    room = Path(tempfile.mkdtemp(prefix='create-water-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
