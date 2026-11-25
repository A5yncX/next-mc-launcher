"""Check a pipe tee, a kinetic valve, exact fluid conservation and restart on two Horizon clients."""
import argparse
import asyncio
from pathlib import Path
import socket
import tempfile

from generate_full_registry import create_ids
from generate_pumpkin_data import CLIENT, read_json
from smoke_core import CONFIG, DATA, HERE, ROOT, server, until
from smoke_depot import inventory_is
from smoke_drain import WATER
from smoke_drivetrain import watch
from smoke_placement import aim, coords, eventually, state_on
from smoke_pump import volume
from smoke_tank import NAME as TANK

PUMP, VALVE, TEE = (-268, 78, -108), (-266, 78, -108), (-264, 78, -108)
SOURCE, EAST, NORTH = (-270, 78, -108), (-263, 78, -108), (-264, 78, -109)
VALVE_ID = 'create:fluid_valve'
PIPE_ID = 'create:fluid_pipe'
STRAIGHT = f'{PIPE_ID}[down=false,east=true,north=false,south=false,up=false,waterlogged=false,west=true]'
TEE_STATE = STRAIGHT.replace('north=false', 'north=true')


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    ids = create_ids(read_json(CLIENT / 'registries.json'), 'block_entity_type')
    targets = {pos: (name, ids[name]) for pos, name in [(VALVE, VALVE_ID), (SOURCE, TANK), (EAST, TANK), (NORTH, TANK)]}

    async def amounts(peers, source, east, north):
        def snapshot():
            return [tuple(volume(o, pos) for pos in (SOURCE, EAST, NORTH)) for o in peers]
        try:
            await until(lambda: all(actual == (source, east, north) for actual in snapshot()),
                        f'exactly {source}/{east}/{north} mB', 25)
        except TimeoutError as exc:
            raise AssertionError(f'{exc}: received {snapshot()} mB') from exc

    async with server(args, room, port, 'pipes') as (send, _):
        async with watch(args, room, port, 'Builder', targets) as (build, first), \
                watch(args, room, port, 'Witness', targets) as (see, second):
            peers = (first, second)
            await asyncio.sleep(2)
            send('fill -273 77 -112 -261 77 -102 stone', 'fill -273 78 -112 -261 81 -102 air',
                 f'setblock {coords(PUMP)} create:mechanical_pump[facing=east,waterlogged=false]',
                 'setblock -269 78 -109 create:creative_motor[facing=east]',
                 'setblock -268 78 -109 create:cogwheel[axis=x,waterlogged=false]',
                 f'setblock {coords(VALVE)} {VALVE_ID}[axis_along_first=false,enabled=false,facing=north,waterlogged=false]',
                 *(f'setblock {x} 78 -108 {STRAIGHT}' for x in (-269, -267, -265)),
                 *(f'setblock {coords(pos)} {TANK}' for pos in (SOURCE, EAST, NORTH)),
                 'tp Builder -263.5 78 -105.8', 'gamemode survival Builder', f'give Builder {PIPE_ID}')
            await amounts(peers, 0, 0, 0)
            await inventory_is(build, PIPE_ID, 1)
            await eventually(lambda: build('state'), lambda row: abs(row['player']['position'][0] + 263.5) < .1, 'Builder at the junction')
            await build(f'select {PIPE_ID}')
            await asyncio.sleep(.4)
            await aim(build, (-263.5, 77.999, -107.5), (-264, 77, -108))
            await build('use-item')
            await state_on(see, TEE, TEE_STATE)
            await inventory_is(build, PIPE_ID, 0)
            send('tp Builder -270.5 78 -105.8')
            await eventually(lambda: build('state'), lambda row: abs(row['player']['position'][0] + 270.5) < .1, 'Builder at the source tank')

            async def pour():
                send(f'give Builder {WATER}')
                await inventory_is(build, WATER, 1)
                await build(f'select {WATER}')
                await asyncio.sleep(.3)
                await aim(build, (-269.5, 78.55, -107.05), SOURCE)
                await build('use-item')
                await inventory_is(build, WATER, 0)

            await pour()
            await amounts(peers, 1000, 0, 0)
            await asyncio.sleep(.6)
            assert all(volume(o, SOURCE) == 1000 for o in peers), 'closed valve leaked'
            send('setblock -266 77 -108 create:creative_motor[facing=up]')
            await until(lambda: all(o.tags.get(VALVE, {}).get('Pointer', {}).get('Value') == 1 for o in peers), 'valve opens at positive RPM')
            await amounts(peers, 0, 500, 500)
            send('setblock -265 78 -108 air')
            await asyncio.sleep(.5)
            await pour()
            await amounts(peers, 1000, 500, 500)
            await asyncio.sleep(.6)
            assert all(volume(o, SOURCE) == 1000 for o in peers), 'flow crossed a missing pipe'
            send(f'setblock -265 78 -108 {STRAIGHT}')
            await amounts(peers, 0, 1000, 1000)
            send('setblock -266 77 -108 stone', 'setblock -266 79 -108 create:creative_motor[facing=down]')
            await until(lambda: all(o.tags.get(VALVE, {}).get('Pointer', {}).get('Value') == 0 for o in peers), 'valve closes at negative RPM')

    reconnect = room / 'reconnect'
    reconnect.mkdir()
    async with server(args, room, port, 'restart') as (_, __):
        async with watch(args, reconnect, port, 'Builder', targets) as (_, again):
            await amounts((again,), 0, 1000, 1000)
            assert again.tags.get(VALVE, {}).get('Pointer', {}).get('Value') == 0
            print('PASS: tee split 2000 mB, no leak with a closed valve or broken pipe, saved valve and amounts', flush=True)


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
    room = Path(tempfile.mkdtemp(prefix='create-pipes-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
