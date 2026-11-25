"""Check network readings, real comparator output, and reload using Horizon clients."""
import argparse
import asyncio
import math
from itertools import product
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
from smoke_passive_recipes import slots
from smoke_placement import aim, coords, eventually, state_on

MOTOR = (-270, 78, -108)
SHAFT = (-269, 78, -108)
SPEED = (-268, 78, -108)
STRESS = (-267, 78, -108)
WIRE = (-268, 78, -106)
GAUGES = {SPEED: 'create:speedometer', STRESS: 'create:stressometer'}
TABLE = (-265, 78, -108)
SUFFIX = '[axis_along_first=true,facing=north]'
AXES = {'east': (1, 2), 'west': (1, 2), 'up': (0, 2), 'down': (0, 2),
        'north': (0, 1), 'south': (0, 1)}
MOTOR_FACES = (('east', 'west'), ('up', 'down'), ('south', 'north'))


def orientation_cases():
    for i, (name, facing, first) in enumerate(product(GAUGES.values(), AXES, (True, False))):
        gauge = (-273 + i % 6 * 3, 80, -127 + i // 6 * 3)
        axis = AXES[facing][0 if first else 1]
        reverse = facing in {'west', 'down', 'north'}
        motor = tuple(v + (1 if reverse else -1) * (a == axis) for a, v in enumerate(gauge))
        yield gauge, f'{name}[axis_along_first={str(first).lower()},facing={facing}]', motor, \
            f'create:creative_motor[facing={MOTOR_FACES[axis][reverse]}]', (-32 if reverse else 32)


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    ids = create_ids(read_json(CLIENT / 'registries.json'), 'block_entity_type')
    targets = {pos: (name + SUFFIX, ids[name]) for pos, name in GAUGES.items()}
    cases = list(orientation_cases())
    tracked = targets | {p: (state, ids[state.split('[')[0]]) for p, state, _, _, _ in cases}
    shaft_state = 'create:shaft[axis=x,waterlogged=false]'

    async def verify(clients, powered):
        rpm = 32 if powered else 0
        signal = 7 if powered else 0
        expected_dial = 0.45 + 2 / 70 * 0.30 if powered else 0

        def tags_ok(obs):
            speed, stress = (obs.tags.get(p, {}) for p in (SPEED, STRESS))
            return (speed.get('Speed') == stress.get('Speed') == rpm
                    and math.isclose(speed.get('Value', -1), expected_dial, abs_tol=1e-6)
                    and speed.get('Color') == (0x3FA2FF if powered else 0x3F3F3F)
                    and stress.get('Stress') == stress.get('Value') == 0
                    and stress.get('Capacity') == (32768 if powered else 0))

        await until(lambda: all(tags_ok(obs) for _, obs in clients),
                    f'both gauges report {rpm} RPM and correct dial/capacity', 20)
        for call, _ in clients:
            for pos, (state, _) in targets.items():
                await state_on(call, pos, state)
            await eventually(lambda: call(f'block {coords(WIRE)}'),
                             lambda row: f'power={signal},' in row.get('state', ''),
                             f'physical comparator drives redstone wire at {signal}')

    async def verify_matrix(*clients):
        await until(lambda: all(obs.tags.get(p, {}).get('Speed') == rpm
                              for _, obs in clients for p, _, _, _, rpm in cases),
                    'all 24 gauge states connect on the correct axis with signed speed', 25)
        for call, _ in clients:
            for pos, state, _, _, _ in cases:
                await state_on(call, pos, state)

    async def craft(call, inputs, result):
        await aim(call, (-264.5, 78.6, -107.01), TABLE)
        await call('use-item')
        await eventually(lambda: call('screen'), lambda s: s.get('craft_size') == 3, 'open real crafting table')
        for cell, name in inputs:
            inventory = await inventory_is(call, name, 1)
            source = next(s['slot'] for s in inventory['hotbar'] + inventory['main'] if s['item'] == name)
            await call(f'click-slot {source}')
            await call(f'click-slot {cell}')
        await eventually(lambda: call('menu'), lambda m: slots(m).get(200) == (result, 1), result)
        await asyncio.sleep(.25)
        await call('click-slot 200 shift')
        await call('key esc tap')
        for _, name in inputs:
            await inventory_is(call, name, 0)
        await inventory_is(call, result, 1)

    async with server(args, room, port, 'gauges') as (send, _):
        generate(room / 'create-lab/datapacks/create-passive')
        send('datapack enable "file/create-passive"')
        async with watch(args, room, port, 'Builder', tracked) as builder, \
                watch(args, room, port, 'Witness', tracked) as witness:
            await asyncio.sleep(2)
            send('fill -273 77 -112 -261 77 -102 stone', 'fill -273 78 -112 -261 81 -102 air',
                 f'setblock {coords(MOTOR)} create:creative_motor[facing=east]',
                 f'setblock {coords(SHAFT)} {shaft_state}',
                 'setblock -268 78 -107 minecraft:comparator[facing=north]',
                 f'setblock {coords(WIRE)} minecraft:redstone_wire',
                 *(f'setblock {coords(pos)} {state}' for pos, (state, _) in targets.items()))
            await verify((builder, witness), True)
            send(f'setblock {coords(SHAFT)} minecraft:air')
            await verify((builder, witness), False)
            send(f'setblock {coords(SHAFT)} {shaft_state}')
            await verify((builder, witness), True)
            send('fill -274 79 -128 -257 81 -117 air')
            await state_on(builder[0], cases[0][0], 'minecraft:air')
            send(*(cmd for gauge, state, motor, motor_state, _ in cases for cmd in (
                f'setblock {coords(motor)} {motor_state}', f'setblock {coords(gauge)} {state}')))
            await verify_matrix(builder, witness)
    reconnect = room / 'reconnect'
    reconnect.mkdir()
    async with server(args, room, port, 'restart') as (send, _):
        async with watch(args, reconnect, port, 'Builder', tracked) as builder:
            await verify((builder,), True)
            await verify_matrix(builder)
            call, _ = builder
            speed, stress = GAUGES.values()
            send('gamemode survival Builder', 'give Builder minecraft:iron_pickaxe 1',
                 'give Builder minecraft:compass 1', 'give Builder create:andesite_casing 1',
                 f'setblock {coords(TABLE)} minecraft:crafting_table')
            await inventory_is(call, 'minecraft:iron_pickaxe', 1)
            await state_on(call, TABLE, 'minecraft:crafting_table')
            await move(call, send, (-264.5, 78, -105.5))
            await craft(call, [(100, 'minecraft:compass'), (103, 'create:andesite_casing')], speed)
            await craft(call, [(104, speed)], stress)
            await craft(call, [(105, stress)], speed)
            print('PASS: speedometer crafted from compass/casing; both gauge conversions cost one item', flush=True)
            await move(call, send, (-267.5, 78, -104.5))
            await call('select minecraft:iron_pickaxe')
            await asyncio.sleep(.3)
            for pos, name in GAUGES.items():
                drops = (await call(f'break {coords(pos)} --timeout 18'))['drops']
                assert drops == {name: 1}, (pos, drops)
            print('PASS: all orientations survived restart; both gauges returned one exact drop', flush=True)
            await move(call, send, (-266.5, 78, -107.5))
            assert (await aim(call, (-268.01, 78.5, -107.5), SHAFT))['face'] == 'east'
            await call(f'select {speed}')
            await asyncio.sleep(.3)
            await call('use-item')
            await state_on(call, SPEED, f'{speed}[axis_along_first=true,facing=south]')
            unattached = (-264, 78, -110)
            await move(call, send, (-263.5, 78, -107.5))
            assert (await aim(call, (-263.5, 77.99, -109.5), (-264, 77, -110)))['face'] == 'up'
            send(f'give Builder {stress} 1')
            await eventually(lambda: call('inventory'),
                             lambda inv: any(s.get('item') == stress for s in inv['hotbar']), 'stressometer received')
            await call(f'select {stress}')
            await asyncio.sleep(.3)
            await call('use-item')
            await state_on(call, unattached, f'{stress}[axis_along_first=true,facing=up]')
            print('PASS: both gauges placed in Survival, on a shaft and unconnected floor', flush=True)


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
    room = Path(tempfile.mkdtemp(prefix='create-gauges-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
