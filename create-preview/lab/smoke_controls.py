"""Check redstone clutch/gearshift and their signed port speeds with two Horizon clients."""
import argparse
import asyncio
from pathlib import Path
import socket
import tempfile

from generate_full_registry import create_ids
from generate_pumpkin_data import CLIENT, read_json
from smoke_core import CONFIG, DATA, HERE, ROOT, server, until
from smoke_drivetrain import watch
from smoke_placement import coords, state_on

CONTROLS = {(-268, 78, -109): 'clutch', (-268, 78, -105): 'gearshift'}


def facing_speeds(observer, pos, west, east):
    return observer.tags.get(pos, {}).get('create_horizon', {}).get('Ports', {}) == {
        'west': west, 'east': east, 'down': 0, 'up': 0, 'north': 0, 'south': 0,
    }


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    ids = create_ids(read_json(CLIENT / 'registries.json'), 'block_entity_type')
    shaft = 'create:shaft[axis=x,waterlogged=false]'
    targets = {(x + offset, y, z): (name, ids[name.split('[')[0]])
               for (x, y, z), block in CONTROLS.items()
               for offset, name in [(-1, 'create:creative_motor[facing=east]'),
                                    (0, f'create:{block}'), (1, shaft)]}

    async def verify(clients, powered):
        for call, _ in clients:
            for pos, block in CONTROLS.items():
                await state_on(call, pos, f'create:{block}[axis=x,powered={str(powered).lower()}]')
        expected = {pos: (0 if block == 'clutch' else -32) if powered else 32
                    for pos, block in CONTROLS.items()}

        def correct(observer):
            for (x, y, z), east in expected.items():
                pos = (x, y, z)
                shaft_pos = (x + 1, y, z)
                if not facing_speeds(observer, pos, 32, east):
                    return False
                if observer.tags.get(shaft_pos, {}).get('Speed') != east:
                    return False
            return True

        await until(lambda: all(correct(observer) for _, observer in clients),
                    f'powered={powered}: output speeds {list(expected.values())}', 25)

    async with server(args, room, port, 'controls') as (send, _):
        async with watch(args, room, port, 'Builder', targets) as builder, \
                watch(args, room, port, 'Witness', targets) as witness:
            await asyncio.sleep(2)
            send('fill -272 77 -112 -259 77 -100 stone', 'fill -272 78 -112 -259 81 -100 air',
                 *(f'setblock {coords(pos)} {value}{"[axis=x,powered=false]" if pos in CONTROLS else ""}'
                   for pos, (value, _) in targets.items()))
            await verify((builder, witness), False)
            for power in ('redstone_block', 'air', 'redstone_block'):
                send(*(f'setblock {x} {y + 1} {z} {power}' for x, y, z in CONTROLS))
                await verify((builder, witness), power != 'air')
    reconnect = room / 'reconnect'
    reconnect.mkdir()
    async with server(args, room, port, 'restart') as (_, __):
        async with watch(args, reconnect, port, 'Builder', targets) as builder:
            await verify((builder,), True)


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
    room = Path(tempfile.mkdtemp(prefix='create-controls-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
