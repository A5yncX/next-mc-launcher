"""Verify the single-block fluid tank's bucket exchange and save on real clients."""
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
from smoke_drain import BUCKET, LAVA, WATER
from smoke_drivetrain import watch
from smoke_placement import aim, coords, eventually

POS = (-268, 78, -108)
WIRE = (-268, 78, -106)
HIT = (-267.5, 78.55, -107.5)
NAME = 'create:fluid_tank'
CAPACITY_KEY = 'create_horizon_tank_capacity'


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    ids = create_ids(read_json(CLIENT / 'registries.json'), 'block_entity_type')
    targets = {POS: (NAME, ids[NAME])}

    async def check(peers, amount, fluid='minecraft:water'):
        expected = dict(Fluid=dict(id=fluid, amount=amount)) if amount else {}

        def matches(obs):
            tag = obs.tags.get(POS, {})
            return (tag.get('TankContent') == expected and tag.get(CAPACITY_KEY) == 8000
                    and tag.get('Controller') == [] and tag.get('Size') == tag.get('Height') == 1)

        await until(lambda: all(matches(obs) for _, obs in peers), f'client tank {fluid} {amount}/8000 mB')
        signal = 14 * amount // 8000 + bool(amount)
        for call, _ in peers:
            await eventually(lambda: call(f'block {coords(WIRE)}'),
                             lambda row: f'power={signal},' in row.get('state', ''),
                             f'physical comparator output {signal}')

    async def use(call, item):
        await call(f'select {item}')
        await call('use-item')

    async with server(args, room, port, 'tank') as (send, _):
        generate(room / 'create-lab/datapacks/create-passive')
        send('datapack enable "file/create-passive"')
        async with watch(args, room, port, 'Builder', targets) as builder, \
                watch(args, room, port, 'Witness', targets) as witness:
            build, _ = builder
            peers = (builder, witness)
            await asyncio.sleep(2)
            send('fill -273 77 -112 -261 77 -102 stone', 'fill -273 78 -112 -261 81 -102 air',
                 'setblock -268 78 -107 minecraft:comparator[facing=north]',
                 f'setblock {coords(WIRE)} minecraft:redstone_wire', f'setblock {coords(POS)} {NAME}',
                 'tp Builder -270.5 78 -107.5', 'gamemode survival Builder',
                 f'give Builder {WATER} 8', f'give Builder {LAVA} 1')
            await inventory_is(build, WATER, 8)
            await inventory_is(build, LAVA, 1)
            await aim(build, HIT, POS)
            for filled in range(1, 9):
                await use(build, WATER)
                await inventory_is(build, BUCKET, filled)
                await check(peers, 1000 * filled)
                if filled == 7:
                    await use(build, LAVA)
                    await asyncio.sleep(.5)
                    await inventory_is(build, LAVA, 1)
                    await check(peers, 7000)
            await inventory_is(build, WATER, 0)

    reconnect = room / 'reconnect'
    reconnect.mkdir()
    async with server(args, room, port, 'restart') as (_, __):
        async with watch(args, reconnect, port, 'Builder', targets) as builder:
            build, _ = builder
            await check((builder,), 8000)
            await aim(build, HIT, POS)
            for removed in range(1, 9):
                await use(build, BUCKET)
                await inventory_is(build, WATER, removed)
                await check((builder,), 8000 - 1000 * removed)
            await use(build, LAVA)
            await inventory_is(build, BUCKET, 1)
            await check((builder,), 1000, 'minecraft:lava')
            await use(build, BUCKET)
            await inventory_is(build, LAVA, 1)
            await check((builder,), 0)
            print('PASS: full-tank restart, all 8 original water buckets and lava recovered', flush=True)


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
    room = Path(tempfile.mkdtemp(prefix='create-tank-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
