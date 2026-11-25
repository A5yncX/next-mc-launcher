"""Mine real Create piston/rope parts and verify structural cleanup on two Horizon clients."""
import argparse
import asyncio
from pathlib import Path
import socket
import tempfile

from generate_passive_data import generate
from smoke_core import CONFIG, DATA, HERE, ROOT, server
from smoke_depot import inventory_is
from smoke_encasing import move
from smoke_placement import client, coords, eventually, state_on

PISTON = (-269, 78, -110)
POLES = [(-269, 78, -109), (-269, 78, -108)]
HEAD = (-269, 78, -107)
PULLEY = (-264, 81, -110)
COLUMN = [(-264, y, -110) for y in (80, 79, 78)]
OTHER = (-263, 78, -110)
BASE = 'create:mechanical_piston[axis_along_first=true,facing=south,state=extended]'
POLE = 'create:piston_extension_pole[facing=south,waterlogged=false]'
ROPE = 'create:rope[waterlogged=false]'
MAGNET = 'create:pulley_magnet[waterlogged=false]'


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    generate(room / 'create-lab/datapacks/create-passive')
    states = {PISTON: BASE, **dict.fromkeys(POLES, POLE),
              HEAD: 'create:mechanical_piston_head[facing=south,type=normal,waterlogged=false]',
              PULLEY: 'create:rope_pulley[axis=x]', COLUMN[0]: ROPE, COLUMN[1]: ROPE,
              COLUMN[2]: MAGNET, OTHER: MAGNET}

    async def verify(call):
        await state_on(call, PISTON, BASE.replace('extended', 'retracted'))
        await state_on(call, PULLEY, states[PULLEY])
        await state_on(call, OTHER, MAGNET)
        for p in [*POLES, HEAD, *COLUMN]:
            await state_on(call, p, 'minecraft:air')

    async with server(args, room, port, 'cleanup') as (send, _):
        send('datapack enable "file/create-passive"')
        async with client(args, room, port, 'Builder') as (build, _), client(args, room, port, 'Witness') as (see, _):
            await asyncio.sleep(2)
            send('fill -272 77 -113 -261 77 -104 stone', 'fill -272 78 -113 -261 83 -104 air',
                 *(f'setblock {coords(p)} {s}' for p, s in states.items()),
                 'gamemode survival Builder', 'item replace entity Builder hotbar.0 with minecraft:iron_pickaxe')
            for p, s in states.items():
                await state_on(see, p, s)
            await inventory_is(build, 'minecraft:iron_pickaxe', 1)
            await build('select minecraft:iron_pickaxe')
            await move(build, send, (-267.5, 78, -108.5))
            await build(f'break {coords(POLES[1])} --timeout 18')
            await state_on(see, PISTON, BASE.replace('extended', 'retracted'))
            for p in [*POLES, HEAD]:
                await state_on(see, p, 'minecraft:air')
            async def drops():
                name = 'create:piston_extension_pole'
                return (
                    sum(e['item']['count'] for e in (await see('entities 16 minecraft:item'))['entities']
                        if e['item']['item'] == name),
                    (await build('inventory'))['counts'].get(name, 0),
                )
            await eventually(drops, lambda counts: sum(counts) == 3,
                             'exactly three poles across dropped items and player pickup')
            await move(build, send, (-263.5, 78, -107.5))
            await build(f'break {coords(COLUMN[1])} --timeout 18')
            for call in (build, see):
                await verify(call)
            print('PASS: piston retracts, three poles drop, dry rope column clears, nearby magnet remains on both clients', flush=True)
    reconnect = room / 'reconnect'
    reconnect.mkdir()
    async with server(args, room, port, 'restart'):
        async with client(args, reconnect, port, 'Builder') as (build, _):
            await verify(build)
    print('PASS: retraction and both removals persist after restart', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', type=Path, default=ROOT / 'research_create_rust/.create-lab-build/game-target/fast/horizon-client.exe')
    parser.add_argument('--pumpkin', type=Path, default=HERE.parent / '.cache/core-target/debug/pumpkin.exe')
    parser.add_argument('--resources', type=Path, default=DATA / 'resources-create-v4')
    parser.add_argument('--create-jar', type=Path)
    args = parser.parse_args()
    for attr, path in vars(args).items():
        if path is not None:
            setattr(args, attr, path.resolve(strict=True))
    room = Path(tempfile.mkdtemp(prefix='create-actuator-cleanup-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
