"""Case every shaft/cog variant, wrench the ports, reload, and check exact drops."""
import argparse
import asyncio
from pathlib import Path
import socket
import tempfile

from generate_passive_data import generate
from generate_pumpkin_data import CLIENT, read_json
from smoke_chute import watch
from smoke_core import CONFIG, DATA, HERE, ROOT, server, until
from smoke_depot import inventory_is
from smoke_placement import aim, coords, eventually, state_on

PARTS = ('shaft', 'cogwheel', 'large_cogwheel')
CASES = {(-270 + 4 * i, 78, -110 + 4 * row): (casing, part)
         for row, casing in enumerate(('andesite', 'brass')) for i, part in enumerate(PARTS)}
GEAR = (-266, 78, -110)
OUTPUT = (-265, 78, -110)
WRENCH = 'create:wrench'


def state(pos, axis='x', ends=(False, False)):
    casing, part = CASES[pos]
    suffix = '' if part == 'shaft' else f',bottom_shaft={str(ends[1]).lower()},top_shaft={str(ends[0]).lower()}'
    return f'create:{casing}_encased_{part}[axis={axis}{suffix}]'


def bare(part, axis='x'):
    return f'create:{part}[axis={axis},waterlogged=false]'


async def move(call, send, point, player='Builder'):
    send(f'tp {player} {coords(point)}')
    await eventually(lambda: call('state'), lambda r: r.get('player') and all(
        abs(actual - expected) < .2 for actual, expected in zip(r['player']['position'], point)), f'{player} in reach')


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    generate(room / 'create-lab/datapacks/create-passive')
    names = read_json(CLIENT / 'registries.json')['minecraft:block_entity_type']['entries']
    targets = {pos: (name, names[name]['protocol_id']) for pos, name in (
        (GEAR, 'create:andesite_encased_cogwheel'), (OUTPUT, 'create:shaft'))}
    expected = {pos: state(pos, ends=(True, True) if pos == GEAR else (False, False)) for pos in CASES}

    async with server(args, room, port, 'encasing') as (send, _):
        send('datapack enable "file/create-passive"')
        async with watch(args, room, port, 'Builder', targets) as (build, first), \
                watch(args, room, port, 'Witness', targets) as (see, second):
            await asyncio.sleep(2)
            send('fill -272 77 -112 -260 77 -103 stone',
                 'fill -272 78 -112 -260 82 -103 air',
                 *(f'setblock {coords(pos)} {bare(part)}' for pos, (_, part) in CASES.items()),
                 'setblock -267 78 -110 create:creative_motor[facing=east]',
                 f'setblock {coords(OUTPUT)} {bare("shaft")}',
                 'gamemode survival Builder', 'give Builder create:andesite_casing 1',
                 'give Builder create:brass_casing 1', f'give Builder {WRENCH} 1',
                 'give Builder minecraft:iron_pickaxe 1')
            for pos, (casing, part) in CASES.items():
                x, y, z = pos
                await state_on(build, pos, bare(part))
                await move(build, send, (x + .5, y, z + 2.5))
                key = f'create:{casing}_casing'
                await inventory_is(build, key, 1)
                await build(f'select {key}')
                await aim(build, (x + .5, y + .5, z + .5), pos)
                await build('use-item')
                for call in (see, build):
                    await state_on(call, pos, expected[pos])
                await inventory_is(build, key, 1)
            print('PASS: all six right-click encasing variants, no casing consumed', flush=True)
            await until(lambda: all(o.tags.get(OUTPUT, {}).get('Speed') == 32 for o in (first, second)),
                        'connected faces retain shaft power at 32 RPM', 15)
            x, y, z = GEAR
            await move(build, send, (x + 2.25, y, z + .5))
            hit = await aim(build, (x + .99, y + .86, z + .5), GEAR)
            assert hit['face'] == 'east', hit
            await build(f'select {WRENCH}')
            await build('use-item')
            expected[GEAR] = state(GEAR, ends=(False, True))
            for call in (see, build):
                await state_on(call, GEAR, expected[GEAR])
            await until(lambda: all(o.tags.get(OUTPUT, {}).get('Speed') == 0 for o in (first, second)),
                        'closing only the output shaft stops it', 15)
            turn = next(pos for pos, pair in CASES.items() if pair == ('brass', 'cogwheel'))
            x, y, z = turn
            await move(build, send, (x + .5, y, z + 2.5))
            hit = await aim(build, (x + .5, y + .55, z + .99), turn)
            assert hit['face'] == 'south', hit
            await build('use-item')
            expected[turn] = state(turn, axis='y')
            for call in (see, build):
                await state_on(call, turn, expected[turn])

    reconnect = room / 'reconnect'
    reconnect.mkdir()
    async with server(args, room, port, 'restart') as (send, _):
        async with watch(args, reconnect, port, 'Builder', targets) as (build, observed):
            for pos, goal in expected.items():
                await state_on(build, pos, goal)
            await until(lambda: observed.tags.get(OUTPUT, {}).get('Speed') == 0,
                        'closed output remains stopped after restart', 15)
            x, y, z = turn
            await move(build, send, (x + .5, y, z + 2.5))
            await aim(build, (x + .5, y + .55, z + .99), turn)
            await build(f'select {WRENCH}')
            await build('key shift down')
            try:
                await asyncio.sleep(.35)
                await build('use-item')
                await state_on(build, turn, bare('cogwheel', axis='y'))
            finally:
                await build('key shift up')
            pos = next(pos for pos, pair in CASES.items() if pair == ('brass', 'large_cogwheel'))
            x, y, z = pos
            await move(build, send, (x + .5, y, z + 2.5))
            await build('select minecraft:iron_pickaxe')
            result = await build(f'break {coords(pos)} --timeout 18')
            assert result.get('block') == 'minecraft:air' and result['drops'] == {'create:large_cogwheel': 1}, result
            print('PASS: axis and port survive restart; sneak-wrench uncases, mining yields just the gear', flush=True)


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
    room = Path(tempfile.mkdtemp(prefix='create-encasing-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
