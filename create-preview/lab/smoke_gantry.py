"""Exercise a three-piece fixed gantry with two real Horizon clients."""
import argparse
import asyncio
from pathlib import Path
import socket
import tempfile

from generate_full_registry import create_ids
from generate_pumpkin_data import CLIENT, read_json
from smoke_core import CONFIG, DATA, HERE, ROOT, server, until
from smoke_depot import inventory_is
from smoke_drivetrain import watch
from smoke_encasing import move
from smoke_placement import aim, coords, state_on

RAILS = [(-270, 78, -110), (-269, 78, -110), (-268, 78, -110)]
PINION = (-269, 78, -109)
OUTPUT = (-269, 79, -109)
POWER = (-270, 78, -111)
PARTS = ('start', 'middle', 'end')
CARRIAGE = 'create:gantry_carriage[axis_along_first=false,facing=south]'
SHAFT = 'create:shaft[axis=y,waterlogged=false]'


def rail(part, powered=False):
    return f'create:gantry_shaft[facing=east,part={part},powered={str(powered).lower()}]'


def output_rpm(observation, rpm):
    return all(observation.tags.get(p, {}).get('Speed') == rpm for p in (PINION, OUTPUT))


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    ids = create_ids(read_json(CLIENT / 'registries.json'), 'block_entity_type')
    states = {**dict.fromkeys(RAILS, rail('single')), PINION: CARRIAGE, OUTPUT: SHAFT}
    targets = {pos: (state, ids[state.split('[')[0]]) for pos, state in states.items()}

    async def check_states(calls, parts, powered):
        for call in calls:
            for pos, part in zip(RAILS, parts, strict=True):
                await state_on(call, pos, rail(part, powered) if part else 'minecraft:air')
            await state_on(call, PINION, CARRIAGE)

    async with server(args, room, port, 'gantry') as (send, _):
        async with watch(args, room, port, 'Builder', targets) as (build, first), \
                watch(args, room, port, 'Witness', targets) as (see, second):
            await asyncio.sleep(2)
            send('fill -272 77 -113 -260 77 -103 stone', 'fill -272 78 -113 -260 83 -103 air',
                 'setblock -271 78 -110 create:creative_motor[facing=east]',
                 'setblock -265 78 -110 minecraft:stone',
                 *(f'setblock {coords(pos)} {rail("single")}' for pos in RAILS),
                 'gamemode survival Builder', 'give Builder create:gantry_carriage 1')
            await move(build, send, (-264.5, 78, -107.5))
            await build('select create:gantry_carriage')
            await aim(build, (-264.5, 78.5, -109.5), (-265, 78, -110))
            await build('use-item')
            await asyncio.sleep(.5)
            await inventory_is(build, 'create:gantry_carriage', 1)
            await state_on(see, (-265, 78, -109), 'minecraft:air')
            await state_on(see, RAILS[1], rail('middle'))
            await move(build, send, (-268.5, 78, -107.5))
            hit = await aim(build, (-268.5, 78.5, -109.5), RAILS[1])
            assert hit['face'] == 'south', hit
            await build('use-item')
            await check_states((see, build), PARTS, False)
            await inventory_is(build, 'create:gantry_carriage', 0)
            print('PASS: invalid mounting costs nothing; real carriage placement selects the perpendicular shaft', flush=True)
            send(f'setblock {coords(OUTPUT)} {SHAFT}', f'setblock {coords(POWER)} minecraft:redstone_block')
            await check_states((see, build), PARTS, True)
            await until(lambda: all(output_rpm(o, -32) for o in (first, second)), 'powered rail sends -32 RPM through carriage and output')
            send(f'setblock {coords(RAILS[0])} minecraft:air')
            await check_states((see, build), (None, 'start', 'end'), False)
            await until(lambda: all(output_rpm(o, 0) for o in (first, second)), 'separation removes shared redstone and torque')
            send(f'setblock {coords(RAILS[0])} {rail("single")}')
            await check_states((see, build), PARTS, True)
            await until(lambda: all(output_rpm(o, -32) for o in (first, second)), 'restored shared redstone and torque')

    reconnect = room / 'reconnect'
    reconnect.mkdir()
    async with server(args, room, port, 'restart'):
        async with watch(args, reconnect, port, 'Builder', targets) as (build, restored):
            await check_states((build,), PARTS, True)
            await until(lambda: output_rpm(restored, -32), 'restart recovers rail, carriage, and signed output')


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
    room = Path(tempfile.mkdtemp(prefix='create-gantry-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
