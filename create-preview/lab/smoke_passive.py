"""Verify Create materials drop, accept vanilla tools and reload their datapack."""
import argparse
import asyncio
from pathlib import Path
import socket
import tempfile

from generate_passive_data import PASSIVE_BLOCKS, generate
from smoke_core import CONFIG, DATA, HERE, ROOT, server
from smoke_placement import client, coords, eventually, state_on
from smoke_registry import inventory_has

ORE = (-268, 79, -108)
ZINC_ORES = ('zinc_ore', 'deepslate_zinc_ore')
IRON_TIER = (*ZINC_ORES, 'raw_zinc_block', 'zinc_block')
CASINGS = ('andesite_casing', 'brass_casing', 'copper_casing')


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))

    async def mine(call, send, block, tool, expected=None, witness=None):
        name = 'create:' + block
        # Prevent new raw-zinc drops from merging into a previously observed entity.
        send('kill @e[type=minecraft:item]', f'setblock {coords(ORE)} {name}')
        for observer in (call, witness):
            if observer:
                await state_on(observer, ORE, name)
        await call(f'select minecraft:{tool}')
        # Wait for the selected-slot packet before starting the authoritative break.
        await asyncio.sleep(.25)
        result = await call(f'break {coords(ORE)} --timeout 18')
        assert result.get('block') == 'minecraft:air', result
        if witness:
            await state_on(witness, ORE, 'minecraft:air')
        if expected is not None:
            assert result['drops'] == expected, result
            print(f'PASS: {tool} on {block} drops {expected}', flush=True)
        return result['drops']

    async with server(args, room, port, 'passive') as (send, _):
        pack = room / 'create-lab/datapacks/create-passive'
        generate(pack)
        send('datapack enable "file/create-passive"')
        async with client(args, room, port, 'Builder') as (build, _), \
                client(args, room, port, 'Witness') as (see, _):
            await asyncio.sleep(2)
            send('fill -272 77 -111 -261 77 -103 stone', 'fill -272 78 -111 -261 82 -103 air',
                 'tp Builder -270.5 78 -107.5', 'gamemode survival Builder',
                 'give Builder minecraft:stone_pickaxe 1', 'give Builder minecraft:iron_pickaxe 1',
                 'give Builder minecraft:iron_axe 1')
            await eventually(lambda: build('state'), lambda row: abs(row['player']['position'][0] + 270.5) < .1,
                             'Builder in mining range')
            await eventually(lambda: build('inventory'), lambda row: inventory_has(row, 'minecraft:iron_axe'), 'tools received')
            for block in IRON_TIER:
                await mine(build, send, block, 'stone_pickaxe', {}, see)
            for block in PASSIVE_BLOCKS:
                expected = 'create:raw_zinc' if block in ZINC_ORES else 'create:' + block
                await mine(build, send, block, 'iron_pickaxe', {expected: 1}, see)
            for block in CASINGS:
                await mine(build, send, block, 'iron_axe', {'create:' + block: 1}, see)
            await build('select minecraft:iron_pickaxe')
            await asyncio.sleep(.3)  # The console may process its command before the selected-slot packet.
            send('enchant Builder minecraft:fortune 3')
            await eventually(lambda: build('inventory'),
                             lambda row: 'minecraft:fortune' in (row.get('held') or {}).get('components', ''),
                             'the selected iron pickaxe has Fortune III')
            for ore in ZINC_ORES:
                for _ in range(24):
                    drops = await mine(build, send, ore, 'iron_pickaxe', witness=see)
                    assert set(drops) == {'create:raw_zinc'} and 1 <= drops['create:raw_zinc'] <= 4, drops
                    if drops['create:raw_zinc'] > 1:
                        print(f'PASS: Fortune III on {ore} gave {drops}', flush=True)
                        break
                else:
                    raise AssertionError(f'Fortune III gave no bonus for {ore} in 24 isolated trials')
            send('clear Builder minecraft:iron_pickaxe', 'give Builder minecraft:iron_pickaxe 1')
            await asyncio.sleep(.5)
            await build('select minecraft:iron_pickaxe')
            await asyncio.sleep(.3)
            send('enchant Builder minecraft:silk_touch 1')
            await eventually(lambda: build('inventory'),
                             lambda row: 'minecraft:silk_touch' in (row.get('held') or {}).get('components', ''),
                             'the selected replacement pickaxe has Silk Touch')
            for ore in ZINC_ORES:
                await mine(build, send, ore, 'iron_pickaxe', {'create:' + ore: 1}, see)

    reconnect = room / 'reconnect'
    reconnect.mkdir()
    async with server(args, room, port, 'restart') as (send, _):
        async with client(args, reconnect, port, 'Builder') as (build, _):
            await mine(build, send, 'zinc_ore', 'iron_pickaxe', {'create:zinc_ore': 1})


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
    room = Path(tempfile.mkdtemp(prefix='create-passive-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
