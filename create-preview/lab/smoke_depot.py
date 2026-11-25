"""Exercise Depot insertion, replacement, reload, and drops using two real clients."""
import argparse
import asyncio
from pathlib import Path
import socket
import tempfile

from generate_passive_data import generate
from smoke_core import CONFIG, DATA, HERE, ROOT, server
from smoke_placement import aim, client, coords, eventually, state_on

DEPOT = (-268, 78, -108)
DEPOT_STATE = 'create:depot[waterlogged=false]'
TOP = (-267.5, 78.80, -107.5)


def count(status, item):
    for group in ('hotbar', 'main'):
        for entry in status[group]:
            if entry['item'] == item:
                yield entry['count']


async def inventory_is(call, item, amount):
    return await eventually(lambda: call('inventory'), lambda row: sum(count(row, item)) == amount,
                            f'{amount} × {item}')


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    async with server(args, room, port, 'depot') as (send, _):
        generate(room / 'create-lab/datapacks/create-passive')
        send('datapack enable "file/create-passive"')
        async with client(args, room, port, 'Builder') as (build, _), \
                client(args, room, port, 'Witness') as (see, _):
            await asyncio.sleep(2)
            send('fill -272 77 -112 -261 77 -103 stone', 'fill -272 78 -112 -261 82 -103 air',
                 f'setblock {coords(DEPOT)} create:depot', 'tp Builder -270.5 78 -107.5',
                 'gamemode survival Builder', 'give Builder minecraft:iron_ingot 3', 'give Builder minecraft:gold_ingot 5')
            await state_on(see, DEPOT, DEPOT_STATE)
            await inventory_is(build, 'minecraft:iron_ingot', 3)
            await inventory_is(build, 'minecraft:gold_ingot', 5)
            await build('select minecraft:iron_ingot')
            hit = await aim(build, TOP, DEPOT)
            assert hit['face'] == 'up', hit
            await build('use-item')
            await inventory_is(build, 'minecraft:iron_ingot', 0)
            await build('select minecraft:gold_ingot')
            await build('use-item')
            await inventory_is(build, 'minecraft:iron_ingot', 3)
            await inventory_is(build, 'minecraft:gold_ingot', 0)

    reconnect = room / 'reconnect'
    reconnect.mkdir()
    async with server(args, room, port, 'restart') as (send, _):
        async with client(args, reconnect, port, 'Builder') as (build, _):
            await state_on(build, DEPOT, DEPOT_STATE)
            await inventory_is(build, 'minecraft:gold_ingot', 0)
            # Select an empty slot, then take the stored stack without putting anything back.
            status = await build('inventory')
            index = next(entry['slot'] for entry in status['hotbar'] if entry['item'] is None)
            await build(f'select {index + 1}')
            hit = await aim(build, TOP, DEPOT)
            assert hit['face'] == 'up', hit
            await build('use-item')
            await inventory_is(build, 'minecraft:gold_ingot', 5)
            await build('select minecraft:gold_ingot')
            await build('use-item')
            await inventory_is(build, 'minecraft:gold_ingot', 0)
            send(f'setblock {coords(DEPOT)} air')
            await state_on(build, DEPOT, 'minecraft:air')
            await eventually(lambda: build('entities 8 minecraft:item'), lambda row: sum(
                item['item']['count'] for item in row['entities'] if item['item']['item'] == 'minecraft:gold_ingot'
            ) == 5, 'breaking Depot dropped all five stored ingots')


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
    room = Path(tempfile.mkdtemp(prefix='create-depot-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
