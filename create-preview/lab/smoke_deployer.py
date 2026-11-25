"""Drive a real belt and deployer, preserving its hand and held cargo across restart."""
import argparse
import asyncio
from pathlib import Path
import socket
import tempfile

from generate_full_registry import create_ids
from generate_passive_data import generate
from generate_pumpkin_data import CLIENT, read_json
from smoke_belt import BELT, CONNECTOR, OUTLETS, PARTS, SHAFT, contents, state
from smoke_core import CONFIG, DATA, HERE, ROOT, server, until
from smoke_depot import inventory_is
from smoke_drivetrain import watch
from smoke_encasing import move
from smoke_placement import aim, coords, state_on

DEPLOYER = (-267, 80, -108)
MOTOR = (-267, 80, -109)
PLANKS = 'minecraft:oak_planks'
INPUT = 'create:shaft'
OUTPUT = 'create:cogwheel'
LOCK = (-267, 81, -108)
DE_STATE = 'create:deployer[axis_along_first=false,facing=down]'


def hand(observer):
    return observer.tags.get(DEPLOYER, {}).get('HeldItem', {}).get('count', 0)


def amount(observer, item):
    return sum(count for name, count, _ in contents(observer) if name == item)


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    generate(room / 'create-lab/datapacks/create-passive')
    ids = create_ids(read_json(CLIENT / 'registries.json'), 'block_entity_type')
    targets = {p: (state(part), ids['create:belt']) for p, part in zip(BELT, PARTS, strict=True)}
    targets[DEPLOYER] = (DE_STATE, ids['create:deployer'])

    async with server(args, room, port, 'deployer') as (send, _):
        send('datapack enable "file/create-passive"')
        async with watch(args, room, port, 'Builder', targets) as (build, first), \
                watch(args, room, port, 'Witness', targets) as (see, second):
            await asyncio.sleep(2)
            send('fill -272 77 -111 -261 77 -103 stone', 'fill -272 78 -111 -261 83 -103 air',
                 'setblock -269 78 -109 create:creative_motor[facing=south]',
                 *(f'setblock {coords(p)} {SHAFT}' for p in (BELT[0], BELT[-1])),
                 *(f'setblock {coords(p)} minecraft:stone' for p in OUTLETS),
                 f'setblock {coords(DEPLOYER)} {DE_STATE}',
                 f'setblock {coords(MOTOR)} create:creative_motor[facing=south]',
                 'gamemode survival Builder', f'item replace entity Builder hotbar.0 with {CONNECTOR}',
                 f'item replace entity Builder hotbar.1 with {PLANKS} 2')
            for p in (BELT[0], BELT[-1]):
                await state_on(see, p, SHAFT)
            await state_on(see, DEPLOYER, DE_STATE)
            await move(build, send, (-269.5, 78, -105.5))
            await inventory_is(build, CONNECTOR, 1)
            await build(f'select {CONNECTOR}')
            for p in (BELT[0], BELT[-1]):
                await aim(build, (p[0] + .5, p[1] + .5, p[2] + .5), p)
                await build('use-item')
                await asyncio.sleep(.5)
            await state_on(see, BELT[1], state('middle'))
            for o in (first, second):
                await until(lambda: all(abs(o.tags.get(p, {}).get('Speed', 0)) == 32
                                        for p in (BELT[0], DEPLOYER)), 'belt and deployer both run at 32 RPM')
            await move(build, send, (-267.5, 78, -105.5))
            await inventory_is(build, PLANKS, 2)
            await build(f'select {PLANKS}')
            await aim(build, (-266.5, 80.12, -107.98), DEPLOYER)
            await build('use-item')
            await until(lambda: hand(first) == hand(second) == 2, 'both clients see the two planks inside the deployer')
            await inventory_is(build, PLANKS, 0)
            # Drop just before the robot relative to the actual solved belt speed.
            x = BELT[1 if first.tags[BELT[0]]['Speed'] < 0 else 3][0] + .5
            send(f'summon minecraft:item {x} 79.15 -107.5 {{Item:{{id:"{INPUT}",count:1}},PickupDelay:32767s}}')
            await until(lambda: all(amount(o, OUTPUT) == 1 and hand(o) == 1 for o in (first, second)),
                        'both clients see one cogwheel after one plank and one shaft')
            send(f'setblock {coords(LOCK)} minecraft:redstone_block')
            await until(lambda: first.tags.get(DEPLOYER, {}).get('Powered') == 1, 'redstone locks next stroke')
            send(f'summon minecraft:item {x} 79.15 -107.5 {{Item:{{id:"{INPUT}",count:1}},PickupDelay:32767s}}')
            await until(lambda: all(amount(o, INPUT) == 1 and amount(o, OUTPUT) == 1 and hand(o) == 1
                                    for o in (first, second)), 'locked deployer does not consume the second shaft')
            print('PASS: real hand insertion, one shaft + one plank -> one cogwheel, redstone stops next stroke on both clients')
    reconnect = room / 'reconnect'
    reconnect.mkdir()
    async with server(args, room, port, 'restart'):
        async with watch(args, reconnect, port, 'Builder', targets) as (_, saved):
            await until(lambda: hand(saved) == 1 and amount(saved, INPUT) == 1 and amount(saved, OUTPUT) == 1,
                        'both belt stacks and final hand item survive restart')
    print('PASS: exact deployer hand and belt contents survive restart')


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
    room = Path(tempfile.mkdtemp(prefix='create-deployer-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
