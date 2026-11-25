"""Prove powered transfer between two adjacent Create tanks with the real server and clients."""
import argparse
import asyncio
from pathlib import Path
import socket
import tempfile

from generate_full_registry import create_ids
from generate_pumpkin_data import CLIENT, read_json
from smoke_core import CONFIG, DATA, HERE, ROOT, server, until
from smoke_depot import inventory_is
from smoke_drain import BUCKET, WATER
from smoke_drivetrain import watch
from smoke_placement import aim, coords
from smoke_tank import NAME as TANK

PUMP = (-268, 78, -108)
LEFT = (-269, 78, -108)
RIGHT = (-267, 78, -108)
MOTOR = (-269, 78, -109)
GEAR = (-268, 78, -109)
NAME = 'create:mechanical_pump'
WRENCH = 'create:wrench'
GEAR_STATE = 'create:cogwheel[axis=x,waterlogged=false]'


def volume(obs, pos):
    tag = obs.tags.get(pos, {}).get('TankContent')
    if tag is None:
        return -1
    if not tag:
        return 0
    assert tag['Fluid']['id'] == 'minecraft:water', tag
    return tag['Fluid']['amount']


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    ids = create_ids(read_json(CLIENT / 'registries.json'), 'block_entity_type')
    targets = {pos: (name, ids[name]) for pos, name in [(PUMP, NAME), (LEFT, TANK), (RIGHT, TANK)]}

    async def check(peers, left, right):
        await until(lambda: all((volume(o, LEFT), volume(o, RIGHT)) == (left, right) for o in peers),
                    f'tanks report exactly {left} + {right} mB of water')

    async with server(args, room, port, 'pump') as (send, _):
        async with watch(args, room, port, 'Builder', targets) as (build, first), \
                watch(args, room, port, 'Witness', targets) as (_, second):
            await asyncio.sleep(2)
            send('fill -273 77 -112 -261 77 -102 stone', 'fill -273 78 -112 -261 81 -102 air',
                 f'setblock {coords(LEFT)} {TANK}', f'setblock {coords(RIGHT)} {TANK}',
                 f'setblock {coords(PUMP)} {NAME}[facing=east,waterlogged=false]',
                 f'setblock {coords(MOTOR)} create:creative_motor[facing=east]',
                 'tp Builder -267.5 78 -104.5', 'gamemode survival Builder',
                 f'give Builder {WATER}', f'give Builder {WRENCH}')
            peers = (first, second)
            await check(peers, 0, 0)
            await inventory_is(build, WATER, 1)
            await aim(build, (-268.5, 78.5, -107.5), LEFT)
            await build(f'select {WATER}')
            await build('use-item')
            await inventory_is(build, BUCKET, 1)
            await check(peers, 1000, 0)
            await asyncio.sleep(1)
            assert all(volume(o, RIGHT) == 0 for o in peers), 'unpowered pump moved fluid'
            send(f'setblock {coords(GEAR)} {GEAR_STATE}')
            await until(lambda: all(o.tags.get(PUMP, {}).get('Speed') == -32.0 for o in peers),
                        'both pumps show -32 RPM from the adjacent cog')
            await check(peers, 0, 1000)
            await aim(build, (-267.5, 78.5, -107.5), PUMP)
            await build(f'select {WRENCH}')
            await build('use-item')
            await check(peers, 1000, 0)
            send(f'setblock {coords(GEAR)} air')
            await until(lambda: all(o.tags.get(PUMP, {}).get('Speed') == 0.0 for o in peers),
                        'removing its cog stops the pump')

    reconnect = room / 'reconnect'
    reconnect.mkdir()
    async with server(args, room, port, 'restart') as (send, _):
        async with watch(args, reconnect, port, 'Builder', targets) as (build, again):
            await check((again,), 1000, 0)
            await asyncio.sleep(2)
            send('tp Builder -269.5 78 -105.8')
            await build(f'select {BUCKET}')
            await asyncio.sleep(.5)
            await aim(build, (-268.5, 78.55, -107.05), LEFT)
            await build('use-item')
            await inventory_is(build, WATER, 1)
            await check((again,), 0, 0)
            print('PASS: exactly one water bucket pumped both ways and recovered after restart', flush=True)


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
    room = Path(tempfile.mkdtemp(prefix='create-pump-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
