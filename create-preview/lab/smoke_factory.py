"""Exercise authoritative millstone recipes and fan airflow with two real clients."""
import argparse
import asyncio
from pathlib import Path
import socket
import struct
import tempfile

from generate_full_registry import create_ids
from generate_pumpkin_data import CLIENT, read_json
from smoke_core import CONFIG, DATA, HERE, ROOT, server, until
from smoke_depot import inventory_is
from smoke_drivetrain import watch
from smoke_placement import aim, coords, state_on

MILL = (-269, 79, -108)
MILL_MOTOR = (-269, 78, -108)
FAN = (-266, 78, -108)
FAN_MOTOR = (-267, 78, -108)
WALL = (-264, 78, -108)
MOTOR_STATE = 'create:creative_motor[facing=east]'


def reach(observer, position):
    current = observer.tags.get(position, {}).get('CreateHorizonAirCurrent', [])
    return struct.unpack('>f', struct.pack('>i', current[3]))[0] if len(current) >= 8 else None


def output(observer, name):
    items = observer.tags.get(MILL, {}).get('OutputInventory', {}).get('Items', [])
    return sum(stack['count'] for stack in items if stack.get('id') == name)


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    ids = create_ids(read_json(CLIENT / 'registries.json'), 'block_entity_type')
    targets = {
        MILL: ('create:millstone', ids['create:millstone']),
        FAN: ('create:encased_fan[facing=east]', ids['create:encased_fan']),
    }
    async with server(args, room, port, 'factory') as (send, _):
        async with watch(args, room, port, 'Builder', targets) as (build, first), \
                watch(args, room, port, 'Witness', targets) as (see, second):
            await asyncio.sleep(2)
            send('fill -272 77 -112 -257 77 -104 stone', 'fill -272 78 -112 -257 83 -104 air',
                 *(f'setblock {coords(pos)} {state}' for pos, (state, _) in targets.items()),
                 f'setblock {coords(FAN_MOTOR)} {MOTOR_STATE}',
                 'tp Builder -268.5 80.1 -107.5', 'gamemode survival Builder', 'give Builder minecraft:andesite 2')
            peers = (first, second)
            await until(lambda: all(reach(o, FAN) == 5.125 for o in peers), 'both clients see unobstructed fan at 32 RPM', 20)
            send(f'setblock {coords(WALL)} stone')
            await until(lambda: all(reach(o, FAN) == 1.0 for o in peers), 'wall shortens both clients’ current to one block', 15)
            send(f'setblock {coords(WALL)} air')
            await until(lambda: all(reach(o, FAN) == 5.125 for o in peers), 'removing wall restores airflow', 15)
            send(f'setblock {coords(FAN_MOTOR)} air')
            await until(lambda: all(reach(o, FAN) is None and o.tags[FAN].get('Speed') == 0 for o in peers), 'fan stops when power is removed', 15)

            await inventory_is(build, 'minecraft:andesite', 2)
            await build('select minecraft:andesite')
            hit = await aim(build, (-268.5, 79.99, -107.5), MILL)
            assert hit['face'] == 'up', hit
            await build('use-item')
            await inventory_is(build, 'minecraft:andesite', 0)
            await asyncio.sleep(1)
            assert all(output(o, 'minecraft:cobblestone') == 0 for o in peers)
            send(f'setblock {coords(MILL_MOTOR)} create:creative_motor[facing=up]')
            await until(lambda: all(abs(o.tags.get(MILL, {}).get('Speed', 0)) == 32 for o in peers), 'millstone obtains RPM from a real kinetic network', 20)
            await until(lambda: all(output(o, 'minecraft:cobblestone') == 2 for o in peers), 'exactly two andesite become two cobblestone on both clients', 25)

    reconnect = room / 'reconnect'
    reconnect.mkdir()
    async with server(args, room, port, 'restart') as (send, _):
        async with watch(args, reconnect, port, 'Builder', targets) as (build, peer):
            await state_on(build, MILL, 'create:millstone')
            await until(lambda: output(peer, 'minecraft:cobblestone') == 2, 'milling output survived restart', 15)
            await asyncio.sleep(1)
            send('tp Builder -268.5 80.1 -107.5')
            await inventory_is(build, 'minecraft:cobblestone', 0)
            await aim(build, (-268.5, 79.99, -107.5), MILL)
            await build('use-item')
            await inventory_is(build, 'minecraft:cobblestone', 2)
            print('PASS: both stored cobblestone recovered after restart', flush=True)


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
    room = Path(tempfile.mkdtemp(prefix='create-factory-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
