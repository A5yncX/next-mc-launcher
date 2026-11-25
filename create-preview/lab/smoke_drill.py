"""Check the stationary mechanical drill, crack packets, protected targets and restart."""
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
DRILL = (-268, 78, -108)
TARGET = (-267, 78, -108)
NAME = 'create:mechanical_drill'
POWER = 'create:creative_motor[facing=east]'


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    ids = create_ids(read_json(CLIENT / 'registries.json'), 'block_entity_type')
    targets = {DRILL: (NAME, ids[NAME]), TARGET: ('minecraft:stone', 0)}

    async def speed(peers, rpm):
        await until(lambda: all(o.tags.get(DRILL, {}).get('Speed') == rpm for o in peers), f'drill speed {rpm} RPM', 18)

    async def same_block(peers, pos, name):
        for call, _ in peers:
            await state_on(call, pos, name)

    def has_stage(obs):
        return any(0 <= stage <= 9 for stage in obs.cracks.get(TARGET, []))

    async with server(args, room, port, 'drill') as (send, _):
        async with watch(args, room, port, 'Builder', targets) as builder, \
                watch(args, room, port, 'Witness', targets) as witness:
            peers = (builder, witness)
            build, _ = builder
            observations = [obs for _, obs in peers]
            await asyncio.sleep(2)
            send('fill -273 77 -112 -260 77 -104 stone', 'fill -273 78 -112 -260 82 -104 air',
                 f'setblock {coords(DRILL)} {NAME}[facing=east]',
                 f'setblock {coords(TARGET)} stone', 'tp Builder -268.5 78 -104.5')
            await same_block(peers, TARGET, 'minecraft:stone')
            await speed(observations, 0)
            send(f'setblock {coords(MOTOR)} {POWER}')
            await speed(observations, 32)
            await until(lambda: all(has_stage(obs) for obs in observations), 'both clients receive actual drill crack stages', 18)
            await same_block(peers, TARGET, 'minecraft:air')
            await until(lambda: all(obs.cracks[TARGET][-1] < 0 for obs in observations), 'break clears both crack overlays', 10)
            await eventually(lambda: build('entities 8 minecraft:item'), lambda row: sum(
                item['item']['count'] for item in row['entities'] if item['item']['item'] == 'minecraft:cobblestone'
            ) == 1, 'exactly one cobblestone drop near the broken stone')
            send(f'setblock {coords(TARGET)} bedrock')
            await same_block(peers, TARGET, 'minecraft:bedrock')
            await asyncio.sleep(2)
            await same_block(peers, TARGET, 'minecraft:bedrock')
            send(f'setblock {coords(TARGET)} chest')
            chest = 'minecraft:chest[facing=north,type=single,waterlogged=false]'
            await same_block(peers, TARGET, chest)
            await asyncio.sleep(2)
            await same_block(peers, TARGET, chest)
            send(f'setblock {coords(MOTOR)} air', f'setblock {coords(TARGET)} stone')
            await speed(observations, 0)
            await same_block(peers, TARGET, 'minecraft:stone')

    reconnect = room / 'reconnect'
    reconnect.mkdir()
    async with server(args, room, port, 'restart') as (send, _):
        async with watch(args, reconnect, port, 'Builder', targets) as builder:
            await same_block((builder,), TARGET, 'minecraft:stone')
            await speed((builder[1],), 0)
            send(f'setblock {coords(MOTOR)} {POWER}')
            await same_block((builder,), TARGET, 'minecraft:air')
            print('PASS: restored drill resumes only after restoring power', flush=True)


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
    room = Path(tempfile.mkdtemp(prefix='create-drill-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
