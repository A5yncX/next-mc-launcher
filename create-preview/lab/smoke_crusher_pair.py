"""Verify crusher formation, rotation, recovery and cleanup from two Horizon clients."""
import argparse
import asyncio
from pathlib import Path
import socket
import tempfile

from generate_full_registry import create_ids
from generate_pumpkin_data import CLIENT, read_json
from smoke_core import CONFIG, DATA, HERE, ROOT, server, until
from smoke_drivetrain import watch
from smoke_placement import coords, eventually, state_on

WEST, CENTER, EAST = (-269, 78, -108), (-268, 78, -108), (-267, 78, -108)
MOTOR_WEST, MOTOR_EAST = (-269, 78, -107), (-267, 78, -109)
WHEEL = 'create:crushing_wheel'
CONTROLLER = WHEEL + '_controller'
GRAVEL, SAND = 'minecraft:gravel', 'minecraft:sand'


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    ids = create_ids(read_json(CLIENT / 'registries.json'), 'block_entity_type')
    targets = {pos: (name, ids[name]) for pos, name in ((WEST, WHEEL), (CENTER, CONTROLLER), (EAST, WHEEL))}

    async def both(peers, pos, state):
        for call, _ in peers:
            await state_on(call, pos, state)

    async def drive(peers, west, east, active):
        await until(lambda: all(o.tags.get(WEST, {}).get('Speed') == west
                                and o.tags.get(EAST, {}).get('Speed') == east
                                and abs(o.tags.get(CENTER, {}).get('Speed', -1) - (.64 if active else 0)) < .0001
                                for _, o in peers), f'wheel RPM {west}/{east}, controller enabled={active}', 25)
        await both(peers, CENTER, f'{CONTROLLER}[facing=down,valid={str(active).lower()}]')

    def sand(peer):
        tags = peer[1].tags.get(CENTER, {}).get('Inventory', {})
        return sum(row.get('count', 0) for row in tags.get('Items', []) if row.get('id') == SAND)

    async with server(args, room, port, 'crusher-pair') as (send, _):
        async with watch(args, room, port, 'Builder', targets) as builder, \
                watch(args, room, port, 'Witness', targets) as witness:
            peers = (builder, witness)
            await asyncio.sleep(2)
            send('fill -273 77 -112 -260 77 -103 stone', 'fill -273 78 -112 -260 82 -103 air')
            await both(peers, CENTER, 'minecraft:air')
            await asyncio.sleep(1)
            send(f'setblock {coords(CENTER)} stone')
            await both(peers, CENTER, 'minecraft:stone')
            send(*(f'setblock {coords(pos)} {WHEEL}[axis=z]' for pos in (WEST, EAST)))
            await asyncio.sleep(.7)
            await both(peers, CENTER, 'minecraft:stone')
            send(f'setblock {coords(CENTER)} air')
            await drive(peers, 0, 0, False)
            send(f'setblock {coords(MOTOR_WEST)} create:creative_motor[facing=north]',
                 f'setblock {coords(MOTOR_EAST)} create:creative_motor[facing=south]')
            await drive(peers, -32, 32, True)
            send(f'setblock {coords(MOTOR_WEST)} air')
            await drive(peers, 0, 32, False)
            send(f'setblock {coords(WEST)} air')
            await both(peers, CENTER, 'minecraft:air')
            send(f'setblock {coords(WEST)} {WHEEL}[axis=z]',
                 f'setblock {coords(MOTOR_WEST)} create:creative_motor[facing=north]')
            await drive(peers, -32, 32, True)
            send('setblock -268 76 -108 stone',
                 f'summon minecraft:item -267.5 79.4 -107.5 {{Item:{{id:"{GRAVEL}",count:2}},PickupDelay:32767s}}')
            await until(lambda: all(sand(peer) == 2 for peer in peers),
                        'two gravel became two sand, held behind the blocked output', 32)

    reconnect = room / 'reconnect'
    reconnect.mkdir()
    async with server(args, room, port, 'restart') as (send, _):
        async with watch(args, reconnect, port, 'Builder', targets) as builder:
            await drive((builder,), -32, 32, True)
            await until(lambda: sand(builder) == 2, 'blocked output persisted after restart')
            send('setblock -268 77 -108 air')
            await eventually(lambda: builder[0]('entities 12 minecraft:item'), lambda row: sum(
                item['item']['count'] for item in row['entities'] if item['item']['item'] == SAND
            ) == 2, 'exactly two sand ejected into the clear space after restart')
            await until(lambda: sand(builder) == 0, 'no sand left in controller after ejection')


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
    room = Path(tempfile.mkdtemp(prefix='create-crusher-pair-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
