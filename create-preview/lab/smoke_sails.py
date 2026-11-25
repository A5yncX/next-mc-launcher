"""Check sail painting, same-plane extension, drops and reload on real clients."""
import argparse
import asyncio
from pathlib import Path
import socket
import tempfile

from generate_passive_data import generate
from smoke_core import CONFIG, DATA, HERE, ROOT, server
from smoke_depot import inventory_is
from smoke_placement import aim, client, coords, eventually, state_on

BASE = (-268, 78, -108)
SIDE = (-267, 78, -108)
ABOVE = (-268, 79, -108)
FLIPPED = (-269, 78, -108)
WHITE, RED, FRAME = ('create:white_sail', 'create:red_sail', 'create:sail_frame')
DYE, SHEARS = ('minecraft:red_dye', 'minecraft:shears')


def state(name, direction='south'):
    return f'{name}[facing={direction}]'


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    async with server(args, room, port, 'sails') as (send, _):
        generate(room / 'create-lab/datapacks/create-passive')
        send('datapack enable "file/create-passive"')
        async with client(args, room, port, 'Builder') as (build, _), \
                client(args, room, port, 'Witness') as (see, _):
            await asyncio.sleep(2)
            send('fill -273 77 -113 -261 77 -102 stone', 'fill -273 78 -113 -261 82 -102 air',
                 f'setblock {coords(BASE)} {state(WHITE)}', f'setblock {coords(SIDE)} {state(WHITE)}',
                 f'setblock {coords(FLIPPED)} {state(WHITE, "north")}',
                 'tp Builder -267.5 78 -104.5', 'gamemode survival Builder',
                 f'give Builder {DYE} 1', f'give Builder {SHEARS} 1', f'give Builder {WHITE} 1')
            await eventually(lambda: build('state'), lambda r: abs(r['player']['position'][2] + 104.5) < .1,
                             'Builder reached sail fixture')
            await inventory_is(build, DYE, 1)
            await build(f'select {DYE}')
            await aim(build, (-267.2, 78.5, -107.5), BASE)
            await build('use-item')
            for call in (build, see):
                await state_on(call, BASE, state(RED))
                await state_on(call, SIDE, state(WHITE))
            await build('use-item')
            for call in (build, see):
                await state_on(call, SIDE, state(RED))
                await state_on(call, FLIPPED, state(WHITE, 'north'))
            await inventory_is(build, DYE, 1)
            print('PASS: preserve facing, same-plane brush and unchanged dye count', flush=True)

            await build(f'select {SHEARS}')
            await aim(build, (-266.5, 78.5, -107.5), SIDE)
            await build('use-item')
            for call in (build, see):
                await state_on(call, SIDE, state(FRAME))
            await build(f'select {DYE}')
            await build('use-item')
            await build(f'select {WHITE}')
            await aim(build, (-267.5, 78.88, -107.5), BASE)
            await build('use-item')
            for call in (build, see):
                await state_on(call, SIDE, state(FRAME))
                await state_on(call, ABOVE, state(WHITE))
            await inventory_is(build, WHITE, 0)
            print('PASS: shears conversion, frame dye barrier and extension consume one sail', flush=True)

    reconnect = room / 'reconnect'
    reconnect.mkdir()
    async with server(args, room, port, 'restart') as (_, __):
        async with client(args, reconnect, port, 'Builder') as (build, _):
            await state_on(build, BASE, state(RED))
            await state_on(build, SIDE, state(FRAME))
            await state_on(build, ABOVE, state(WHITE))
            await build(f'select {SHEARS}')
            broken = await build(f'break {coords(BASE)} --timeout 18')
            assert broken.get('block') == 'minecraft:air' and broken['drops'] == {WHITE: 1}, broken
            print('PASS: dyed sail survived restart and dropped exactly one white sail', flush=True)


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
    room = Path(tempfile.mkdtemp(prefix='create-sails-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
