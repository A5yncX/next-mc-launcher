"""Exercise a loaded mechanical press, blocked stroke, and exact Depot output across reload."""
import argparse
import asyncio
from pathlib import Path
import socket
import tempfile

from generate_full_registry import create_ids
from generate_passive_data import generate
from generate_pumpkin_data import CLIENT, read_json
from smoke_core import CONFIG, DATA, HERE, ROOT, server, until
from smoke_depot import DEPOT, DEPOT_STATE, TOP, inventory_is
from smoke_drivetrain import watch
from smoke_placement import aim, client, coords, state_on

MOTOR = (-269, 80, -108)
PRESS = (-268, 80, -108)
GAP = (-268, 79, -108)
GAUGE = (-267, 80, -108)
IRON = 'minecraft:iron_ingot'
SHEET = 'create:iron_sheet'


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    ids = create_ids(read_json(CLIENT / 'registries.json'), 'block_entity_type')
    targets = {
        PRESS: ('create:mechanical_press[facing=east]', ids['create:mechanical_press']),
        GAUGE: ('create:stressometer[axis_along_first=true,facing=north]', ids['create:stressometer']),
    }

    async with server(args, room, port, 'press') as (send, _):
        generate(room / 'create-lab/datapacks/create-passive')
        send('datapack enable "file/create-passive"')
        async with watch(args, room, port, 'Builder', targets) as (build, first), \
                watch(args, room, port, 'Witness', targets) as (_, second):
            await asyncio.sleep(2)
            send('fill -272 77 -112 -261 77 -103 stone', 'fill -272 78 -112 -261 82 -103 air',
                 f'setblock {coords(DEPOT)} create:depot', f'setblock {coords(GAP)} stone',
                 f'setblock {coords(MOTOR)} create:creative_motor[facing=east]',
                 *(f'setblock {coords(pos)} {state}' for pos, (state, _) in targets.items()),
                 'tp Builder -270.5 78 -107.5', 'gamemode survival Builder', 'give Builder minecraft:iron_ingot 2')
            peers = (first, second)
            await until(lambda: all(o.tags.get(GAUGE, {}).get('Stress') == 256 for o in peers),
                        'both stressometers read 256 at 32 RPM', 20)
            await inventory_is(build, IRON, 2)
            await build(f'select {IRON}')
            hit = await aim(build, TOP, DEPOT)
            assert hit['face'] == 'up', hit
            await build('use-item')
            await inventory_is(build, IRON, 0)
            await asyncio.sleep(1.5)
            assert all(o.tags[PRESS]['Running'] == 0 for o in peers), [o.tags[PRESS] for o in peers]
            send(f'setblock {coords(GAP)} air')
            await until(lambda: all(o.tags.get(PRESS, {}).get('Running') == 1 for o in peers),
                        'both clients observe press starting', 15)
            # Finished stays set when the next stroke starts.
            await until(lambda: all(o.tags.get(PRESS, {}).get('Finished') == 1
                                    and o.tags[PRESS]['Running'] == 1 for o in peers),
                        'both clients observe the second stroke', 15)
            await until(lambda: all(o.tags[PRESS]['Running'] == 0 for o in peers),
                        'press completed the second stroke', 15)
    reconnect = room / 'reconnect'
    reconnect.mkdir()
    async with server(args, room, port, 'restart') as (_, __):
        async with client(args, reconnect, port, 'Builder') as (build, _):
            await state_on(build, DEPOT, DEPOT_STATE)
            await inventory_is(build, SHEET, 0)
            hit = await aim(build, TOP, DEPOT)
            assert hit['face'] == 'up', hit
            await build('use-item')
            await inventory_is(build, SHEET, 2)
            await inventory_is(build, IRON, 0)
            print('PASS: two consumed ingots, two recovered sheets after restart', flush=True)


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
    room = Path(tempfile.mkdtemp(prefix='create-press-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
