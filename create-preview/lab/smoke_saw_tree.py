"""Verify the stationary saw on two Horizon clients without moving assemblies."""
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

MOTOR = (-269, 78, -108)
SAW = (-268, 78, -108)
CUT = (-267, 78, -108)
LOGS = [(CUT[0], y, CUT[2]) for y in range(78, 81)]
SUPPORT = [(-266, y, -108) for y in range(78, 81)]
NAME = 'create:mechanical_saw'
SAW_STATE = NAME + '[axis_along_first=false,facing=east,flipped=false]'
POWER = 'create:creative_motor[facing=east]'
WOOD = 'minecraft:oak_log[axis=y]'


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    ids = create_ids(read_json(CLIENT / 'registries.json'), 'block_entity_type')
    targets = {SAW: (NAME, ids[NAME]), CUT: ('minecraft:oak_log', 0)}

    async def both(peers, positions, block):
        for call, _ in peers:
            for pos in positions:
                await state_on(call, pos, block)

    async def item_count(call, item_id, count):
        return await eventually(lambda: call('entities 12 minecraft:item'), lambda row: sum(
            item['item']['count'] for item in row['entities'] if item['item']['item'] == item_id
        ) == count, f'{count} drops of {item_id}')

    async with server(args, room, port, 'saw') as (send, _):
        async with watch(args, room, port, 'Builder', targets) as builder, \
                watch(args, room, port, 'Witness', targets) as witness:
            peers = (builder, witness)
            await asyncio.sleep(2)
            send('fill -273 77 -112 -260 77 -104 stone', 'fill -273 78 -112 -260 82 -104 air',
                 'tp Builder -267.5 78 -104.5', f'setblock {coords(SAW)} {SAW_STATE}',
                 *(f'setblock {coords(pos)} {WOOD}' for pos in LOGS), f'setblock {coords(MOTOR)} {POWER}')
            await until(lambda: all(o.tags.get(SAW, {}).get('Speed') == 32 for _, o in peers), '32 RPM on both saw block entities', 18)
            await both(peers, LOGS, 'minecraft:air')
            await item_count(builder[0], 'minecraft:oak_log', 3)
            print('PASS: cut whole unsupported tree and dropped exactly three logs', flush=True)
            send(f'setblock {coords(MOTOR)} air',
                 *(f'setblock {coords(pos)} {WOOD}' for pos in (*LOGS, *SUPPORT)), f'setblock {coords(MOTOR)} {POWER}')
            await both(peers, [CUT], 'minecraft:air')
            await both(peers, [*LOGS[1:], *SUPPORT], WOOD)
            await item_count(builder[0], 'minecraft:oak_log', 4)
            print('PASS: saw removes the struck log but preserves the supported neighbor and canopy', flush=True)
            send(f'setblock {coords(CUT)} stone')
            await both(peers, [CUT], 'minecraft:stone')
            await asyncio.sleep(2)
            await both(peers, [CUT], 'minecraft:stone')

    reconnect = room / 'reconnect'
    reconnect.mkdir()
    async with server(args, room, port, 'restart') as (_, __):
        async with watch(args, reconnect, port, 'Builder', targets) as builder:
            await both((builder,), [*LOGS[1:], *SUPPORT], WOOD)
            await both((builder,), [CUT], 'minecraft:stone')
            await until(lambda: builder[1].tags.get(SAW, {}).get('Speed') == 32, 'restored saw keeps power but does not cut stone')


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
    room = Path(tempfile.mkdtemp(prefix='create-saw-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
