"""Test all six pinned casing recipe variants, inventory and reload on Horizon."""
import argparse
import asyncio
from pathlib import Path
import socket
import tempfile

from generate_passive_data import generate
from smoke_core import CONFIG, DATA, HERE, ROOT, server
from smoke_depot import inventory_is
from smoke_encasing import move
from smoke_placement import aim, client, coords, state_on

INGREDIENTS = [('andesite', 'create:andesite_alloy'), ('brass', 'create:brass_ingot'),
               ('copper', 'minecraft:copper_ingot')]
VARIANTS = ['minecraft:stripped_oak_log[axis=x]', 'minecraft:stripped_spruce_wood[axis=y]']
CASES = {(-270 + 3 * index, 78, -110 + 4 * row): (base, ingredient, f'create:{metal}_casing')
         for row, base in enumerate(VARIANTS) for index, (metal, ingredient) in enumerate(INGREDIENTS)}
UNSTRIPPED = (-261, 78, -110)
SNEAK = (-261, 78, -106)
IRON = {(-269, 78, -112): 'create:industrial_iron_block',
        (-266, 78, -112): 'create:weathered_iron_block'}
WRENCH = 'create:wrench'


async def target(build, send, pos, held):
    x, y, z = pos
    await move(build, send, (x + .5, y, z + 2.5))
    await build(f'select {held}')
    await aim(build, (x + .5, y + .5, z + .5), pos)


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    if args.wrench:
        generate(room / 'create-lab/datapacks/create-passive')
    async with server(args, room, port, 'material') as (send, _):
        if args.wrench:
            send('datapack enable "file/create-passive"')
        async with client(args, room, port, 'Builder') as (build, _), \
                client(args, room, port, 'Witness') as (see, _):
            await asyncio.sleep(2)
            send('fill -272 77 -113 -260 77 -103 stone', 'fill -272 78 -113 -260 82 -103 air',
                 *(f'setblock {coords(pos)} {base}' for pos, (base, _, _) in CASES.items()),
                 f'setblock {coords(UNSTRIPPED)} minecraft:oak_log[axis=y]',
                 f'setblock {coords(SNEAK)} {VARIANTS[0]}', 'gamemode survival Builder',
                 *(f'give Builder {ingredient} 3' for _, ingredient in INGREDIENTS),
                 'give Builder minecraft:stick 1')
            balances = {key: 3 for _, key in INGREDIENTS}
            for pos, base, key in [(UNSTRIPPED, 'minecraft:oak_log[axis=y]', INGREDIENTS[0][1]),
                                   (SNEAK, VARIANTS[0], 'minecraft:stick'),
                                   (SNEAK, VARIANTS[0], INGREDIENTS[0][1])]:
                await state_on(see, pos, base)
                await target(build, send, pos, key)
                sneak = pos == SNEAK and key != 'minecraft:stick'
                if sneak:
                    await build('key shift down')
                try:
                    await asyncio.sleep(.35)
                    await build('use-item')
                    await asyncio.sleep(.35)
                finally:
                    if sneak:
                        await build('key shift up')
                for call in (build, see):
                    await state_on(call, pos, base)
                await inventory_is(build, key, balances.get(key, 1))
            for pos, (base, key, result) in CASES.items():
                await state_on(see, pos, base)
                await target(build, send, pos, key)
                await build('use-item')
                for call in (see, build):
                    await state_on(call, pos, result)
                balances[key] -= 1
                await inventory_is(build, key, balances[key])
            print('PASS: six real survival casing recipes consume one each, three invalid cases do not', flush=True)
            if args.wrench:
                send(f'give Builder {WRENCH} 1', *(f'setblock {coords(p)} {key}' for p, key in IRON.items()))
                await inventory_is(build, WRENCH, 1)
                for p, key in IRON.items():
                    await state_on(see, p, key)
                    await target(build, send, p, WRENCH)
                    await build('use-item')
                    await asyncio.sleep(.35)
                    await state_on(see, p, key)
                    await wrench(build)
                    await state_on(see, p, 'minecraft:air')
                    await inventory_is(build, key, 1)
                await target(build, send, SNEAK, WRENCH)
                await wrench(build)
                await state_on(see, SNEAK, VARIANTS[0])
                send('gamemode creative Builder', *(f'setblock {coords(p)} {key}' for p, key in IRON.items()))
                for p, key in IRON.items():
                    await state_on(see, p, key)
                    await target(build, send, p, WRENCH)
                    await wrench(build)
                    await state_on(see, p, 'minecraft:air')
                    await inventory_is(build, key, 1)
                print('PASS: only tagged iron blocks are picked up when sneaking; one each in Survival, none in Creative', flush=True)

    reconnect = room / 'reconnect'
    reconnect.mkdir()
    async with server(args, room, port, 'restart'):
        async with client(args, reconnect, port, 'Builder') as (build, _):
            for pos, (_, _, result) in CASES.items():
                await state_on(build, pos, result)
            for _, key in INGREDIENTS:
                await inventory_is(build, key, 1)
            if args.wrench:
                for p, key in IRON.items():
                    await state_on(build, p, 'minecraft:air')
                    await inventory_is(build, key, 1)
            print('PASS: all six casings and remaining survival ingredients persist', flush=True)


async def wrench(build):
    await build('key shift down')
    try:
        await asyncio.sleep(.35)
        await build('use-item')
        await asyncio.sleep(.35)
    finally:
        await build('key shift up')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', type=Path, default=ROOT / 'research_create_rust/.create-lab-build/game-target/fast/horizon-client.exe')
    parser.add_argument('--pumpkin', type=Path, default=HERE.parent / '.cache/core-target/debug/pumpkin.exe')
    parser.add_argument('--resources', type=Path, default=DATA / 'resources-create-v4')
    parser.add_argument('--create-jar', type=Path)
    parser.add_argument('--wrench', action='store_true')
    args = parser.parse_args()
    for attr in ('client', 'pumpkin', 'resources', 'create_jar'):
        if path := getattr(args, attr):
            setattr(args, attr, path.resolve(strict=True))
    room = Path(tempfile.mkdtemp(prefix='create-material-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
