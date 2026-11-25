"""Check that real connector use creates and persists a driven horizontal belt."""
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
from smoke_encasing import move
from smoke_placement import aim, coords, eventually, state_on

BELT = [(-269 + i, 78, -108) for i in range(4)]
PARTS = ('start', 'middle', 'middle', 'end')
OUTPUT = (-266, 78, -107)
SHAFT = 'create:shaft[axis=z,waterlogged=false]'
CONNECTOR = 'create:belt_connector'
CARGO = 'minecraft:quartz'
OUTLETS = [(-270, 78, -108), (-265, 78, -108)]


def contents(observer):
    rows = observer.tags.get(BELT[0], {}).get('Inventory', {}).get('Items', [])
    return [(row['Item']['id'], row['Item']['count'], row['Pos']) for row in rows]


def state(part):
    return f'create:belt[casing=false,facing=east,part={part},slope=horizontal,waterlogged=false]'


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    ids = create_ids(read_json(CLIENT / 'registries.json'), 'block_entity_type')
    targets = {p: (state(part), ids['create:belt']) for p, part in zip(BELT, PARTS, strict=True)}
    targets[OUTPUT] = (SHAFT, ids['create:shaft'])

    async def check_line(call):
        for p, part in zip(BELT, PARTS, strict=True):
            await state_on(call, p, state(part))

    def moving(o):
        return all(abs(o.tags.get(p, {}).get('Speed', 0)) == 32 for p in (*BELT, OUTPUT))

    async with server(args, room, port, 'belt') as (send, _):
        generate(room / 'create-lab/datapacks/create-passive')
        send('datapack enable "file/create-passive"')
        async with watch(args, room, port, 'Builder', targets) as (build, first), \
                watch(args, room, port, 'Witness', targets) as (see, second):
            await asyncio.sleep(2)
            send('fill -272 77 -111 -261 77 -103 stone', 'fill -272 78 -111 -261 83 -103 air',
                 'setblock -269 78 -109 create:creative_motor[facing=south]',
                 *(f'setblock {coords(p)} {SHAFT}' for p in (BELT[0], BELT[-1], OUTPUT)),
                 f'setblock {coords(BELT[1])} minecraft:stone',
                 'gamemode survival Builder', f'give Builder {CONNECTOR} 2')
            await move(build, send, (-269.5, 78, -105.5))
            await build(f'select {CONNECTOR}')

            async def click(p):
                await aim(build, (p[0] + .5, p[1] + .5, p[2] + .5), p)
                await build('use-item')
                await asyncio.sleep(.4)

            await state_on(see, BELT[0], SHAFT)
            await click(BELT[0])
            await click(BELT[-1])
            await state_on(see, BELT[1], 'minecraft:stone')
            await state_on(see, BELT[-1], SHAFT)
            await inventory_is(build, CONNECTOR, 2)
            send(f'setblock {coords(BELT[1])} minecraft:air')
            await state_on(see, BELT[1], 'minecraft:air')
            await click(BELT[-1])
            await check_line(see)
            await check_line(build)
            await inventory_is(build, CONNECTOR, 1)
            await until(lambda: moving(first) and moving(second), 'belt and separate output shaft both display 32 RPM')
            print('PASS: blocked connection costs nothing; four created segments cost one connector', flush=True)
            if args.cargo:
                send(*(f'setblock {coords(p)} stone' for p in OUTLETS))
                for p in OUTLETS:
                    await state_on(see, p, 'minecraft:stone')
                send(f'summon minecraft:item -267.5 79.15 -107.5 {{Item:{{id:"{CARGO}",count:7}},PickupDelay:32767s}}')
                await until(lambda: all(contents(o) and contents(o)[0][:2] == (CARGO, 7)
                                        for o in (first, second)), 'both clients see the seven-item stack on belt')
                await until(lambda: all(contents(o) and abs(contents(o)[0][2] - 2.5) >= 1
                                        for o in (first, second)), 'cargo moves from intake toward a blocked end')

    reconnect = room / 'reconnect'
    reconnect.mkdir()
    async with server(args, room, port, 'restart') as (send, _):
        async with watch(args, reconnect, port, 'Builder', targets) as (build, restored):
            await check_line(build)
            await until(lambda: moving(restored), 'belt and shaft regain 32 RPM after restart')
            if args.cargo:
                await until(lambda: contents(restored) and contents(restored)[0][:2] == (CARGO, 7),
                            'restart preserves all seven items at the blocked end')
                # On this east-facing line the shared engine uses the opposite sign for travel.
                exit_pos = OUTLETS[restored.tags[BELT[0]]['Speed'] < 0]
                send(f'setblock {coords(exit_pos)} air')
                await until(lambda: not contents(restored), 'cleared outlet empties the belt')
                await eventually(lambda: build('entities 16 minecraft:item'), lambda row: sum(
                    e['item']['count'] for e in row['entities'] if e['item']['item'] == CARGO
                ) == 7, 'the cleared outlet ejects exactly seven items')
            await move(build, send, (-268.5, 78, -105.5))
            send('give Builder minecraft:iron_pickaxe 1')
            await inventory_is(build, 'minecraft:iron_pickaxe', 1)
            await build('select minecraft:iron_pickaxe')
            result = await build(f'break {coords(BELT[1])} --timeout 18')
            assert result['drops'] == {CONNECTOR: 1}, result
            for p in (BELT[0], BELT[-1]):
                await state_on(build, p, SHAFT)
            for p in BELT[1:-1]:
                await state_on(build, p, 'minecraft:air')
            print('PASS: break returns one connector and restores both pulleys as shafts', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', type=Path, default=ROOT / 'research_create_rust/.create-lab-build/game-target/fast/horizon-client.exe')
    parser.add_argument('--pumpkin', type=Path, default=HERE.parent / '.cache/core-target/debug/pumpkin.exe')
    parser.add_argument('--resources', type=Path, default=DATA / 'resources-create-v4')
    parser.add_argument('--create-jar', type=Path)
    parser.add_argument('--cargo', action='store_true', help='also verify moving cargo, blocked save and ejection')
    args = parser.parse_args()
    for attr in ('client', 'pumpkin', 'resources', 'create_jar'):
        if path := getattr(args, attr):
            setattr(args, attr, path.resolve(strict=True))
    room = Path(tempfile.mkdtemp(prefix='create-belt-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
