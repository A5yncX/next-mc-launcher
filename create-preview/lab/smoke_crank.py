"""Test actual crank placement and clicks, rotation expiry, reload, and support loss."""
import argparse
import asyncio
from pathlib import Path
import socket
import tempfile

from generate_full_registry import create_ids
from generate_passive_data import generate
from generate_pumpkin_data import CLIENT, read_json
from smoke_core import CONFIG, DATA, HERE, ROOT, server, until
from smoke_drivetrain import watch
from smoke_placement import aim, coords, eventually, state_on

CRANK = (-267, 78, -108)
SHAFT = (-268, 78, -108)
OUTPUT = (-269, 78, -108)
CRANK_STATE = 'create:hand_crank[facing=east,waterlogged=false]'
SHAFT_STATE = 'create:shaft[axis=x,waterlogged=false]'


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    ids = create_ids(read_json(CLIENT / 'registries.json'), 'block_entity_type')
    targets = {CRANK: (CRANK_STATE, ids['create:hand_crank']), OUTPUT: (SHAFT_STATE, ids['create:shaft'])}

    async def rpm(clients, speed):
        await until(lambda: all(all((p, kind, speed) in obs.updates for p, (_, kind) in targets.items())
                                for obs in clients), f'both clients saw crank and output at {speed} RPM', 12)

    async with server(args, room, port, 'crank') as (send, _):
        generate(room / 'create-lab/datapacks/create-passive')
        send('datapack enable "file/create-passive"')
        async with watch(args, room, port, 'Builder', targets) as (build, one), \
                watch(args, room, port, 'Witness', targets) as (see, two):
            await asyncio.sleep(2)
            send('fill -273 77 -111 -260 77 -104 stone', 'fill -273 78 -111 -260 81 -104 air',
                 *(f'setblock {coords(p)} {SHAFT_STATE}' for p in (SHAFT, OUTPUT)),
                 'tp Builder -264.5 78 -107.5', 'give Builder create:hand_crank 1')
            await eventually(lambda: build('state'), lambda row: abs(row['player']['position'][0] + 264.5) < .1,
                             'Builder at the crank')
            await state_on(build, SHAFT, SHAFT_STATE)
            await build('select create:hand_crank')
            hit = await aim(build, (-267.02, 78.5, -107.5), SHAFT)
            assert hit['face'] == 'east', hit
            await build('use-item')
            await state_on(build, CRANK, CRANK_STATE)
            await state_on(see, CRANK, CRANK_STATE)
            inventory = await build('inventory')
            index = next(entry['slot'] for entry in inventory['hotbar'] if entry['item'] is None)
            await build(f'select {index + 1}')
            await aim(build, (-266.5, 78.5, -107.5), CRANK)
            for speed in (32, -32):
                for obs in one, two:
                    obs.updates.clear()
                if speed < 0:
                    await build('key shift down')
                    await asyncio.sleep(.25)
                try:
                    await build('use-item')
                    await rpm((one, two), speed)
                    await until(lambda: all((p, kind, 0) in obs.updates[obs.updates.index((p, kind, speed)) + 1:]
                                            for obs in (one, two) for p, (_, kind) in targets.items()),
                                'both clients saw power expire after click', 12)
                finally:
                    if speed < 0:
                        await build('key shift up')

    reconnect = room / 'reconnect'
    reconnect.mkdir()
    async with server(args, room, port, 'restart') as (send, _):
        async with watch(args, reconnect, port, 'Builder', targets) as (build, obs):
            await state_on(build, CRANK, CRANK_STATE)
            await until(lambda: obs.initial.get(CRANK) == (ids['create:hand_crank'], 0), 'restart left crank idle')
            send(f'setblock {coords(SHAFT)} minecraft:air')
            await state_on(build, CRANK, 'minecraft:air')
            await eventually(lambda: build('entities 8 minecraft:item'), lambda row: sum(
                item['item']['count'] for item in row['entities'] if item['item']['item'] == 'create:hand_crank'
            ) == 1, 'support removal dropped exactly one crank')


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
    room = Path(tempfile.mkdtemp(prefix='create-crank-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
