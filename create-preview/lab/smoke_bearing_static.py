"""Verify bearing placement and stationary shaft load, not moving assemblies."""
import argparse
import asyncio
from pathlib import Path
import socket
import tempfile

from generate_full_registry import create_ids
from generate_pumpkin_data import CLIENT, read_json
from smoke_core import CONFIG, DATA, HERE, server, until
from smoke_depot import inventory_is
from smoke_drivetrain import watch
from smoke_encasing import move
from smoke_placement import aim, coords, state_on

NAMES = ('create:mechanical_bearing', 'create:clockwork_bearing', 'create:windmill_bearing')
POINTS = ((-269, 78, -110), (-266, 78, -110), (-263, 78, -110))
FACES = ('east', 'east', 'north')
MOTORS = tuple((x - 1, y, z) for x, y, z in POINTS[:2])
MOTOR = 'create:creative_motor[facing=east]'


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    ids = create_ids(read_json(CLIENT / 'registries.json'), 'block_entity_type')
    states = [f'{name}[facing={facing}]' for name, facing in zip(NAMES, FACES, strict=True)]
    targets = {p: (s, ids[name]) for p, s, name in zip(POINTS[:2], states[:2], NAMES[:2], strict=True)}

    async def check_state(*peers):
        for call, _ in peers:
            for pos, state in zip(POINTS, states, strict=True):
                await state_on(call, pos, state)

    async def check_speed(speed, *peers):
        await until(lambda: all(o.tags.get(p, {}).get('Speed') == speed for _, o in peers for p in POINTS[:2]),
                    f'both powered bearing types: {speed} RPM', 25)

    async with server(args, room, port, 'bearings') as (send, _):
        async with watch(args, room, port, 'Builder', targets) as builder, \
                watch(args, room, port, 'Witness', targets) as witness:
            build, _ = builder
            await asyncio.sleep(2)
            send('fill -272 77 -113 -261 77 -105 stone', 'fill -272 78 -113 -261 82 -105 air',
                 *(f'setblock {coords(pos)} {MOTOR}' for pos in MOTORS),
                 *(f'setblock {x} {y} {z - 1} stone' for x, y, z in POINTS),
                 'gamemode survival Builder', *(f'give Builder {item} 1' for item in NAMES))
            for index, (item, pos) in enumerate(zip(NAMES, POINTS, strict=True)):
                x, y, z = pos
                await inventory_is(build, item, 1)
                await move(build, send, (x + .5, y, z + 3.5))
                await aim(build, (x + .5, y + .6, z - .02), (x, y, z - 1))
                await build(f'select {item}')
                await asyncio.sleep(.3)
                if index == 2:
                    await build('key shift down')
                    await asyncio.sleep(.3)
                try:
                    await build('use-item')
                    await state_on(witness[0], pos, states[index])
                    await inventory_is(build, item, 0)
                finally:
                    if index == 2:
                        await build('key shift up')
            await check_state(builder, witness)
            await check_speed(32, builder, witness)
            send(*(f'setblock {coords(pos)} air' for pos in MOTORS))
            await check_speed(0, builder, witness)
            send(*(f'setblock {coords(pos)} {MOTOR}' for pos in MOTORS))
            await check_speed(32, builder, witness)
    reconnect = room / 'reconnect'
    reconnect.mkdir()
    async with server(args, room, port, 'restart'):
        async with watch(args, reconnect, port, 'Builder', targets) as builder:
            await check_state(builder)
            await check_speed(32, builder)
    print('PASS: three real survival placements and shaft-driven bearing RPM persisted after restart')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', type=Path, default=DATA / 'components/create-atlas-beta.1/target/plain/release/horizon-client.exe')
    parser.add_argument('--pumpkin', type=Path, default=HERE.parent / '.cache/core-target/debug/pumpkin.exe')
    parser.add_argument('--resources', type=Path, default=DATA / 'resources-create-v4')
    parser.add_argument('--create-jar', type=Path)
    args = parser.parse_args()
    for key, path in vars(args).items():
        if path is not None:
            setattr(args, key, path.resolve(strict=True))
    room = Path(tempfile.mkdtemp(prefix='create-bearing-static-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
