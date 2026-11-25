"""Adjust a real Create motor from Horizon's value board, then reconnect after restart."""
import argparse
import asyncio
import json
from pathlib import Path
import socket
import tempfile

from smoke_core import CONFIG, DATA, HERE, ROOT, Observation, TARGETS, proxy, server, until
from smoke_placement import aim, client, coords, eventually, state_on

MOTOR, SHAFT, COG = TARGETS
PLANK = (-264, 78, -108)


def motor_board(log):
    marker = 'Create motor board: '
    rows = [line.split(marker, 1)[1] for line in log.read_text(errors='replace').splitlines()
            if marker in line]
    return json.loads(rows[-1]) if rows else None


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    one, two = Observation('Operator'), Observation('Witness')
    async with server(args, room, port, 'motor') as (send, _):
        a, b = [await asyncio.start_server(lambda r, w, obs=observation: proxy(r, w, port, obs), '127.0.0.1', 0)
                for observation in (one, two)]
        async with a, b, client(args, room, a.sockets[0].getsockname()[1], one.name) as (operate, log), \
                client(args, room, b.sockets[0].getsockname()[1], two.name) as (watch, _):
            await asyncio.sleep(2)
            send('time set noon', 'fill -267 77 -114 -252 77 -103 stone',
                 'fill -267 78 -114 -252 81 -103 air',
                 f'setblock {coords(MOTOR)} create:creative_motor[facing=east]',
                 f'setblock {coords(SHAFT)} create:shaft[axis=x,waterlogged=false]',
                 f'setblock {coords(COG)} create:cogwheel[axis=x,waterlogged=false]',
                 'tp Operator -262.56 78 -107.1', 'give Operator minecraft:oak_planks 4')
            await until(lambda: all((COG, 71, 32.0) in o.updates for o in (one, two)), 'both clients received the initial 32 RPM', 20)
            await eventually(lambda: operate('state'), lambda r: abs(r['player']['position'][0] + 262.56) < .1,
                             'Operator teleported')
            await operate('select minecraft:oak_planks')
            await aim(operate, (-263.5, 77.99, -107.5), (-264, 77, -108))
            await operate('use-item')
            for call in (operate, watch):
                await state_on(call, PLANK, 'minecraft:oak_planks')
            print('PASS: normal oak planks placed by right-click on the same server', flush=True)

            async def adjust(setting, current):
                for o in (one, two):
                    o.updates.clear()
                hit = await aim(operate, (-262.56, 78.5, -109.22), MOTOR)
                assert hit['face'] == 'south', hit
                await operate('mouse right down')
                await operate('wait 14')  # Hold past the board's six-tick open threshold, including when re-opening.
                await until(lambda: (board := motor_board(log)) is not None and board['pos'] == list(MOTOR)
                            and board['value'] == abs(current) and board['row'] == int(current > 0),
                            f'motor board opened at {current:+} RPM', 12)
                board = motor_board(log)
                x, y = board['origin']
                label = board['size'][0] - 318  # two-row motor layout: label + 24 + 294px bar
                value = abs(setting)
                x += label + 18 + ((value - 1) // 32) * 4 + value + 1.5 + 2 + 4
                y += (int(setting > 0) + .5) * 11 - .5
                await operate(f'scroll-at {x} {y} 0')
                await until(lambda: motor_board(log)['value'] == value
                            and motor_board(log)['row'] == int(setting > 0), f'board selected {setting:+} RPM', 8)
                await operate(f'screenshot {(room / ("motor-" + str(setting) + ".png")).as_posix()}')
                await operate(f'click-at {x} {y} right')
                await until(lambda: all(o.motor_settings.get(MOTOR) == setting and
                            (COG, 71, float(setting)) in o.updates and
                            (SHAFT, 138, float(setting)) in o.updates
                            for o in (one, two)), f'both clients received {setting:+} RPM on the shaft and cog', 15)

            await adjust(64, 32)
            await adjust(-96, 64)
            assert not one.error and not two.error, (one.error, two.error)

    after = Observation('AfterRestart')
    async with server(args, room, port, 'restart') as (_, __):
        link = await asyncio.start_server(lambda r, w: proxy(r, w, port, after), '127.0.0.1', 0)
        async with link, client(args, room, link.sockets[0].getsockname()[1], after.name) as (reconnect, _):
            await until(lambda: after.motor_settings.get(MOTOR) == -96 and
                        after.initial == {pos: (kind, -96.0) for pos, (_, kind) in TARGETS.items()},
                        'restart initial chunk: same motor setting and all three RPM values', 25)
            await state_on(reconnect, PLANK, 'minecraft:oak_planks')
            assert not after.error, after.error


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', type=Path, default=ROOT / 'research_create_rust/.create-lab-build/game-target/fast/horizon-client.exe')
    parser.add_argument('--pumpkin', type=Path, default=HERE.parent / '.cache/core-target/debug/pumpkin.exe')
    parser.add_argument('--resources', type=Path, default=DATA / 'resources-create-v4')
    parser.add_argument('--create-jar', type=Path, help='optional, locally obtained Create 6.0.10 asset source')
    args = parser.parse_args()
    for attr in ('client', 'pumpkin', 'resources', 'create_jar'):
        if path := getattr(args, attr):
            setattr(args, attr, path.resolve(strict=True))
    room = Path(tempfile.mkdtemp(prefix='create-motor-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
