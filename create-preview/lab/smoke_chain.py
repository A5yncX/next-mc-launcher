"""Verify linked geometry, adjustable analog ratios, rotation, and reload on two clients."""
import argparse
import asyncio
from pathlib import Path
import socket
import tempfile

from generate_full_registry import create_ids
from generate_passive_data import generate
from generate_pumpkin_data import CLIENT, read_json
from smoke_core import CONFIG, DATA, HERE, ROOT, server, until
from smoke_drivetrain import watch
from smoke_placement import aim, coords, eventually, state_on

MOTOR = (-269, 78, -109)
DRIVE = 'create:encased_chain_drive'
ADJUSTABLE = 'create:adjustable_chain_gearshift'
A = (-268, 78, -109)
B = (-268, 78, -108)
C = (-268, 78, -107)
OUTPUT = (-268, 79, -108)
POWER_A = (-267, 78, -109)
POWER_B = (-267, 78, -108)
SHAFT = 'create:shaft[axis=y,waterlogged=false]'


def chain(name, axis, part, signal=0, first=False):
    boolean = lambda value: str(bool(value)).lower()
    power = f',powered={boolean(signal)}' if name == ADJUSTABLE else ''
    return f'{name}[axis={axis},axis_along_first={boolean(first)},part={part}{power}]'


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    ids = create_ids(read_json(CLIENT / 'registries.json'), 'block_entity_type')
    targets = {A: (ADJUSTABLE, ids[ADJUSTABLE]), B: (ADJUSTABLE, ids[ADJUSTABLE]),
               C: (DRIVE, ids[DRIVE]), OUTPUT: (SHAFT, ids['create:shaft'])}

    async def verify(clients, left, right, rpm, b_part='middle'):
        await until(lambda: all(obs.tags.get(A, {}).get('Signal') == left
                                and obs.tags.get(B, {}).get('Signal') == right
                                and obs.tags.get(OUTPUT, {}).get('Speed') == rpm for _, obs in clients),
                    f'Signals {left}/{right}, output {rpm} RPM', 18)
        for call, _ in clients:
            await state_on(call, A, chain(ADJUSTABLE, 'x', 'start', left))
            await state_on(call, B, chain(ADJUSTABLE, 'y', b_part, right))

    async with server(args, room, port, 'chain') as (send, _):
        generate(room / 'create-lab/datapacks/create-passive')
        send('datapack enable "file/create-passive"')
        async with watch(args, room, port, 'Builder', targets) as builder, \
                watch(args, room, port, 'Witness', targets) as witness:
            build, _ = builder
            clients = (builder, witness)
            await asyncio.sleep(2)
            send('fill -273 77 -112 -260 77 -103 stone', 'fill -273 78 -112 -260 81 -103 air',
                 f'setblock {coords(MOTOR)} create:creative_motor[facing=east]',
                 f'setblock {coords(A)} {chain(ADJUSTABLE, "x", "start")}',
                 f'setblock {coords(B)} {chain(ADJUSTABLE, "y", "end")}',
                 f'setblock {coords(OUTPUT)} {SHAFT}',
                 'tp Builder -267.5 78 -104.5', 'give Builder create:encased_chain_drive 1',
                 'give Builder create:wrench 1')
            await eventually(lambda: build('state'), lambda row: abs(row['player']['position'][2] + 104.5) < .1,
                             'Builder at the chain')
            await verify(clients, 0, 0, 32, 'end')
            await build('select create:encased_chain_drive')
            await aim(build, (-267.5, 77.99, -106.5), (-268, 77, -107))
            await build('use-item')
            # Placement follows look/port; select the explicit horizontal-axis test state afterward.
            await eventually(lambda: build(f'block {coords(C)}'), lambda r: r.get('state', '').startswith(DRIVE),
                             'placed encased drive via right click')
            send(f'setblock {coords(C)} {chain(DRIVE, "x", "end")}')
            await verify(clients, 0, 0, 32)
            for call, _ in clients:
                await state_on(call, C, chain(DRIVE, 'x', 'end'))
            await build('select create:wrench')
            hit = await aim(build, (-267.5, 78.75, -106.2), C)
            assert hit['face'] == 'south', hit
            await build('use-item')
            for call, _ in clients:
                await state_on(call, C, chain(DRIVE, 'y', 'end'))
            send(f'setblock {coords(POWER_B)} minecraft:redstone_block')
            await verify(clients, 0, 15, 16)
            send(f'setblock {coords(POWER_B)} minecraft:air',
                 f'setblock {coords(POWER_A)} minecraft:comparator[facing=east]',
                 'setblock -266 78 -109 minecraft:composter[level=8]')
            await eventually(lambda: build(f'block {coords(POWER_A)}'),
                             lambda row: 'powered=true' in row.get('state', ''), 'comparator powered')
            await verify(clients, 8, 0, 50)
            send(f'setblock {coords(POWER_A)} minecraft:redstone_block')
            await verify(clients, 15, 0, 64)
            send(f'setblock {coords(B)} minecraft:air')
            for call, obs in clients:
                await state_on(call, A, chain(ADJUSTABLE, 'x', 'none', 15))
                await state_on(call, C, chain(DRIVE, 'y', 'none'))
                await until(lambda: obs.tags.get(OUTPUT, {}).get('Speed') == 0, 'broken chain stopped output')
            send(f'setblock {coords(B)} {chain(ADJUSTABLE, "y", "middle")}')
            await verify(clients, 15, 0, 64)
    reconnect = room / 'reconnect'
    reconnect.mkdir()
    async with server(args, room, port, 'restart') as (_, __):
        async with watch(args, reconnect, port, 'Builder', targets) as builder:
            await verify((builder,), 15, 0, 64)


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
    room = Path(tempfile.mkdtemp(prefix='create-chain-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
