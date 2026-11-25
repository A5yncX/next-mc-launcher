"""Verify live water-wheel overload, comparator output, persistence and recovery."""
import argparse
import asyncio
from pathlib import Path
import socket
import tempfile

from generate_full_registry import create_ids
from generate_pumpkin_data import CLIENT, read_json
from smoke_core import CONFIG, DATA, HERE, server, until
from smoke_drivetrain import watch
from smoke_gauges import SUFFIX
from smoke_placement import coords, eventually, state_on
from smoke_water import WHEEL, WHEEL_STATE, SOUTH

GAUGE = (-267, 78, -108)
LOAD = [(-266 + i, 78, -108) for i in range(5)]
CRUSHER = 'create:crushing_wheel[axis=x]'
STRESS = 'create:stressometer' + SUFFIX
WIRE = (-267, 78, -110)


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    ids = create_ids(read_json(CLIENT / 'registries.json'), 'block_entity_type')
    targets = {pos: (state, ids[state.split('[')[0]]) for pos, state in (
        (WHEEL, WHEEL_STATE), (GAUGE, STRESS), *((pos, CRUSHER) for pos in LOAD))}

    async def measure(peers, count):
        rpm = 0 if count == 5 else 8
        value = 1.125 if count == 5 else count / 4
        signal = {3: 11, 4: 14, 5: 15}[count]

        def readings(o):
            gauge = o.tags.get(GAUGE, {})
            return ((gauge.get('Speed'), gauge.get('Stress'), gauge.get('Capacity'), gauge.get('Value'))
                    == (rpm, 64 * count, 256, value)
                    and o.tags.get(WHEEL, {}).get('FlowScore') == 1
                    and all(o.tags.get(p, {}).get('Speed') == rpm for p in [WHEEL, *LOAD[:count]]))

        try:
            await until(lambda: all(readings(o) for _, o in peers),
                        f'{count} loads: {64 * count}/256 SU, {rpm} RPM', 25)
        except TimeoutError as exc:
            raise AssertionError([o.tags for _, o in peers]) from exc
        for call, _ in peers:
            await eventually(lambda: call(f'block {coords(WIRE)}'),
                             lambda row: f'power={signal},' in row.get('state', ''),
                             f'physical comparator drives redstone wire at {signal}')

    async with server(args, room, port, 'overstress') as (send, _):
        async with watch(args, room, port, 'Builder', targets) as builder, \
                watch(args, room, port, 'Witness', targets) as witness:
            await asyncio.sleep(2)
            send('fill -273 77 -112 -260 77 -103 stone', 'fill -273 78 -112 -260 82 -103 air')
            await state_on(builder[0], LOAD[0], 'minecraft:air')
            send(f'setblock {coords(WHEEL)} {WHEEL_STATE}', f'setblock {coords(GAUGE)} {STRESS}',
                 'setblock -267 78 -109 minecraft:comparator[facing=south]',
                 f'setblock {coords(WIRE)} minecraft:redstone_wire',
                 *(f'setblock {coords(p)} {CRUSHER}' for p in LOAD[:3]),
                 'setblock -269 78 -107 stone', 'setblock -267 78 -107 stone', 'setblock -268 78 -106 stone',
                 'setblock -268 79 -107 stone', 'setblock -268 77 -107 minecraft:magma_block',
                 f'setblock {coords(SOUTH)} minecraft:water')
            await state_on(builder[0], SOUTH, 'minecraft:bubble_column[drag=true]')
            await measure((builder, witness), 3)
            send(f'setblock {coords(LOAD[3])} {CRUSHER}')
            await measure((builder, witness), 4)
            send(f'setblock {coords(LOAD[4])} {CRUSHER}')
            await measure((builder, witness), 5)

    reconnect = room / 'reconnect'
    reconnect.mkdir()
    async with server(args, room, port, 'restart') as (send, _):
        async with watch(args, reconnect, port, 'Builder', targets) as builder:
            await measure((builder,), 5)
            send(f'setblock {coords(LOAD[4])} air')
            await measure((builder,), 4)
    print('PASS: both clients saw overload; reload retained it, removing one load restored motion')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', type=Path, default=DATA / 'components/create-atlas-beta.1/target/plain/release/horizon-client.exe')
    parser.add_argument('--pumpkin', type=Path, default=HERE.parent / '.cache/core-target/debug/pumpkin.exe')
    parser.add_argument('--resources', type=Path, default=DATA / 'resources-create-v4')
    parser.add_argument('--create-jar', type=Path)
    args = parser.parse_args()
    for key, path in vars(args).items():
        if path is not None:
            setattr(args, key, path.resolve(strict=True))
    room = Path(tempfile.mkdtemp(prefix='create-overstress-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
