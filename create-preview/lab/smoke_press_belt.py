"""Exercise the server-owned belt strike, including a restart with an unstruck load."""
import argparse
import asyncio
from pathlib import Path
import socket
import tempfile

from generate_full_registry import create_ids
from generate_pumpkin_data import CLIENT, read_json
from smoke_belt import BELT, CONNECTOR, OUTLETS, PARTS, SHAFT, contents, state
from smoke_core import CONFIG, DATA, HERE, server, until
from smoke_depot import inventory_is
from smoke_drivetrain import watch
from smoke_encasing import move
from smoke_placement import aim, coords, state_on
from smoke_press import IRON, SHEET

PRESS = (-267, 80, -108)
MOTOR = (-268, 80, -108)
PRESS_STATE = 'create:mechanical_press[facing=east]'
POWER = 'create:creative_motor[facing=east]'


def count(observer, item):
    return sum(n for name, n, _ in contents(observer) if name == item)


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    ids = create_ids(read_json(CLIENT / 'registries.json'), 'block_entity_type')
    targets = {p: (state(part), ids['create:belt']) for p, part in zip(BELT, PARTS, strict=True)}
    targets[PRESS] = (PRESS_STATE, ids['create:mechanical_press'])

    async with server(args, room, port, 'press-belt') as (send, _):
        async with watch(args, room, port, 'Builder', targets) as (build, first), \
                watch(args, room, port, 'Witness', targets) as (see, second):
            await asyncio.sleep(2)
            send('fill -272 77 -111 -261 77 -103 stone', 'fill -272 78 -111 -261 83 -103 air',
                 'setblock -269 78 -109 create:creative_motor[facing=south]',
                 *(f'setblock {coords(p)} {SHAFT}' for p in (BELT[0], BELT[-1])),
                 *(f'setblock {coords(p)} minecraft:stone' for p in OUTLETS),
                 f'setblock {coords(PRESS)} {PRESS_STATE}', f'setblock {coords(MOTOR)} {POWER}',
                 'gamemode survival Builder', f'item replace entity Builder hotbar.0 with {CONNECTOR}')
            for p in (BELT[0], BELT[-1]):
                await state_on(see, p, SHAFT)
            await move(build, send, (-269.5, 78, -105.5))
            await inventory_is(build, CONNECTOR, 1)
            await build(f'select {CONNECTOR}')
            for p in (BELT[0], BELT[-1]):
                await aim(build, (p[0] + .5, p[1] + .5, p[2] + .5), p)
                await build('use-item')
                await asyncio.sleep(.5)
            for o in (first, second):
                await until(lambda: all(abs(o.tags.get(p, {}).get('Speed', 0)) == 32
                                        for p in (BELT[0], PRESS)), 'belt and press at 32 RPM')
            x = BELT[1 if first.tags[BELT[0]]['Speed'] < 0 else 3][0] + .5
            send(f'summon minecraft:item {x} 79.15 -107.5 {{Item:{{id:"{IRON}",count:2}},PickupDelay:32767s}}')
            await until(lambda: all(o.tags[PRESS].get('Running') == 1 and o.tags[PRESS].get('Mode') == 1
                                    for o in (first, second)), 'both clients see belt press start')
            # Pause both machines so the belt keeps the claimed stack at the midpoint.
            send(f'setblock {coords(MOTOR)} air', 'setblock -269 78 -109 air')
            await until(lambda: all(o.tags[PRESS].get('Speed') == 0 and o.tags[BELT[0]].get('Speed') == 0
                                    for o in (first, second)), 'both machines stopped')
            assert all(count(o, IRON) == 2 and count(o, SHEET) == 0 and o.tags[PRESS].get('Applied') == 0
                       for o in (first, second))

    reconnect = room / 'reconnect'
    reconnect.mkdir()
    async with server(args, room, port, 'restart') as (send, _):
        async with watch(args, reconnect, port, 'Builder', targets) as (_, saved):
            assert count(saved, IRON) == 2 and count(saved, SHEET) == 0 and saved.tags[PRESS]['Mode'] == 1
            await asyncio.sleep(2)
            send(f'setblock {coords(MOTOR)} {POWER}', 'setblock -269 78 -109 create:creative_motor[facing=south]')
            await until(lambda: count(saved, IRON) == 1 and count(saved, SHEET) == 1,
                        'resumed cycle converts only one ingot on the belt')
            await until(lambda: saved.tags[PRESS].get('Running') == 0, 'press finished')
            assert count(saved, IRON) == 1 and count(saved, SHEET) == 1
    print('PASS: belt holds two ingots, persists before strike, resumes to exactly one sheet plus one ingot')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', type=Path, default=DATA / 'components/create-atlas-beta.1/target/plain/release/horizon-client.exe')
    parser.add_argument('--pumpkin', type=Path, default=HERE.parent / '.cache/core-target/debug/pumpkin.exe')
    parser.add_argument('--resources', type=Path, default=DATA / 'resources-create-v4')
    parser.add_argument('--create-jar', type=Path)
    args = parser.parse_args()
    for attr, path in vars(args).items():
        if path is not None:
            setattr(args, attr, path.resolve(strict=True))
    room = Path(tempfile.mkdtemp(prefix='create-press-belt-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
