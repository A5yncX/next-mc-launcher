"""Check hand-draining, comparator output, and reload with two Horizon clients."""
import argparse
import asyncio
from pathlib import Path
import socket
import tempfile

from generate_full_registry import create_ids
from generate_passive_data import generate
from generate_pumpkin_data import CLIENT, read_json
from smoke_core import CONFIG, DATA, HERE, ROOT, server, until
from smoke_depot import inventory_is
from smoke_drivetrain import watch
from smoke_placement import aim, coords, eventually

DRAIN = (-268, 78, -108)
WIRE = (-268, 78, -106)
TOP = (-267.5, 78.80, -107.5)
NAME = 'create:item_drain'
WATER = 'minecraft:water_bucket'
LAVA = 'minecraft:lava_bucket'
BUCKET = 'minecraft:bucket'
POTION = 'minecraft:potion'
GLASS = 'minecraft:glass_bottle'


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    ids = create_ids(read_json(CLIENT / 'registries.json'), 'block_entity_type')
    targets = {DRAIN: (NAME, ids[NAME])}

    async def check(peers, amount, signal):
        def fluid(obs):
            tanks = obs.tags.get(DRAIN, {}).get('Tanks', [])
            if tanks:
                return tanks[0]['TankContent'].get('Fluid', {})
            return None

        expected = dict(id='minecraft:water', amount=amount) if amount else {}
        await until(lambda: all(fluid(obs) == expected for _, obs in peers),
                    f'client tank data contains exactly {amount} mB', 20)
        for call, _ in peers:
            await eventually(lambda: call(f'block {coords(WIRE)}'),
                             lambda row: f'power={signal},' in row.get('state', ''),
                             f'physical comparator output {signal}')

    async with server(args, room, port, 'drain') as (send, _):
        generate(room / 'create-lab/datapacks/create-passive')
        send('datapack enable "file/create-passive"')
        async with watch(args, room, port, 'Builder', targets) as builder, \
                watch(args, room, port, 'Witness', targets) as witness:
            build, _ = builder
            peers = (builder, witness)
            await asyncio.sleep(2)
            send('fill -273 77 -112 -261 77 -102 stone', 'fill -273 78 -112 -261 81 -102 air',
                 'setblock -268 78 -107 minecraft:comparator[facing=north]',
                 f'setblock {coords(WIRE)} minecraft:redstone_wire',
                 f'setblock {coords(DRAIN)} {NAME}', 'tp Builder -270.5 78 -107.5',
                 'gamemode survival Builder', f'give Builder {WATER} 2', f'give Builder {LAVA} 1',
                 f'give Builder {POTION}[minecraft:potion_contents={{potion:"minecraft:water"}}] 3')
            await inventory_is(build, WATER, 2)
            await inventory_is(build, LAVA, 1)
            await inventory_is(build, POTION, 3)
            await aim(build, TOP, DRAIN)
            await build(f'select {WATER}')
            await build('use-item')
            await check(peers, 1000, 10)
            await inventory_is(build, BUCKET, 1)
            await inventory_is(build, WATER, 1)

            # A second bucket does not fit. A different fluid cannot mix.
            await build(f'select {WATER}')
            await build('use-item')
            await build(f'select {LAVA}')
            await build('use-item')
            await asyncio.sleep(.5)
            await check(peers, 1000, 10)
            await inventory_is(build, WATER, 1)
            await inventory_is(build, LAVA, 1)

            for poured in (1, 2):
                await build(f'select {POTION}')
                await build('use-item')
                await inventory_is(build, GLASS, poured)
                await check(peers, 1000 + 250 * poured, 12 if poured == 1 else 15)
            await build(f'select {POTION}')
            await build('use-item')
            await asyncio.sleep(.5)
            await inventory_is(build, POTION, 1)
            await check(peers, 1500, 15)

    reconnect = room / 'reconnect'
    reconnect.mkdir()
    async with server(args, room, port, 'restart') as (_, __):
        async with watch(args, reconnect, port, 'Builder', targets) as builder:
            await check((builder,), 1500, 15)
            await inventory_is(builder[0], POTION, 1)
            await inventory_is(builder[0], GLASS, 2)
            print('PASS: fluid and empty containers survive restart', flush=True)


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
    room = Path(tempfile.mkdtemp(prefix='create-drain-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
