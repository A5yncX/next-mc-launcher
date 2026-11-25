"""Exercise a tank controller through its child, real client packets and restart."""
import argparse
import asyncio
from pathlib import Path
import socket
import tempfile

from generate_full_registry import create_ids
from generate_pumpkin_data import CLIENT, read_json
from smoke_core import CONFIG, DATA, HERE, ROOT, server, until
from smoke_depot import inventory_is
from smoke_drain import BUCKET, LAVA, WATER
from smoke_drivetrain import watch
from smoke_placement import aim, coords, eventually, state_on
from smoke_pipes import STRAIGHT
from smoke_tank import CAPACITY_KEY, NAME, POS

TOP = POS[0], POS[1] + 1, POS[2]
WIRE = TOP[0], TOP[1], TOP[2] + 2
CORNERS = [(-265, 78, -108), (-264, 78, -108), (-265, 78, -107), (-264, 78, -107)]
REMOTE, REMOTE_TOP = (-272, 78, -108), (-272, 79, -108)
WRENCH = 'create:wrench'


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    ids = create_ids(read_json(CLIENT / 'registries.json'), 'block_entity_type')
    targets = {p: (NAME, ids[NAME]) for p in (POS, TOP, *CORNERS, REMOTE, REMOTE_TOP)}

    async def shape(peers, root, parts, width, height, amount=0, fluid='minecraft:water', window=1):
        expected = dict(Fluid=dict(id=fluid, amount=amount)) if amount else {}

        def matches(obs):
            tag = obs.tags.get(root, {})
            return (tag.get('TankContent') == expected and tag.get(CAPACITY_KEY) == 8000
                    and tag.get('Controller') == [] and tag.get('Size') == width
                    and tag.get('Height') == height and tag.get('Window') == window
                    and all(obs.tags.get(part, {}).get('Controller') == list(root)
                            and 'TankContent' not in obs.tags.get(part, {}) for part in parts))

        await until(lambda: all(matches(obs) for _, obs in peers),
                    f'{width}x{width}x{height} controller at {root}, {amount} mB of {fluid}, window={window}')

    async def click(call, item, target=TOP):
        await call(f'select {item}')
        await asyncio.sleep(.25)
        await aim(call, (target[0] + .5, target[1] + .45, target[2] + .5), target)
        await call('use-item')

    async def signal(call, value):
        await eventually(lambda: call(f'block {coords(WIRE)}'),
                         lambda row: f'power={value},' in row.get('state', ''),
                         f'comparator reads controller through child: {value}')

    async with server(args, room, port, 'multitank') as (send, _):
        async with watch(args, room, port, 'Builder', targets) as builder, \
                watch(args, room, port, 'Witness', targets) as witness:
            peers = (builder, witness)
            build, _ = builder
            await asyncio.sleep(2)
            send('fill -272 77 -110 -261 77 -104 stone', 'fill -272 78 -110 -261 82 -104 air',
                 *(f'setblock {coords(p)} {NAME}' for p in (POS, TOP, *CORNERS)),
                 'fill -268 78 -107 -268 78 -106 stone',
                 'setblock -268 79 -107 minecraft:comparator[facing=north]',
                 f'setblock {coords(WIRE)} minecraft:redstone_wire',
                 'tp Builder -270.5 78 -107.5', 'gamemode survival Builder',
                 f'give Builder {WATER} 8', f'give Builder {WRENCH}')
            await shape(peers, POS, (TOP,), 1, 2)
            await shape(peers, CORNERS[0], CORNERS[1:], 2, 1)
            await inventory_is(build, WATER, 8)
            for count in range(8):
                await click(build, WATER)
                await inventory_is(build, WATER, 7 - count)
            send(f'clear Builder {BUCKET}', f'give Builder {WATER}')
            await inventory_is(build, BUCKET, 0)
            await inventory_is(build, WATER, 1)
            await click(build, WATER)
            await inventory_is(build, WATER, 0)
            await shape(peers, POS, (TOP,), 1, 2, 9000)
            await signal(build, 8)
            await click(build, WRENCH)
            await shape(peers, POS, (TOP,), 1, 2, 9000, window=0)
            await click(build, WRENCH)
            await shape(peers, POS, (TOP,), 1, 2, 9000)

            # The pump only touches upper children through straight pipes.
            send(*(f'setblock {coords(p)} {NAME}' for p in (REMOTE, REMOTE_TOP)),
                 'setblock -271 79 -109 create:creative_motor[facing=east]',
                 'setblock -270 79 -109 create:cogwheel[axis=x,waterlogged=false]',
                 f'setblock -269 79 -108 {STRAIGHT}', f'setblock -271 79 -108 {STRAIGHT}',
                 'setblock -270 79 -108 create:mechanical_pump[facing=west,waterlogged=false]')
            await shape(peers, REMOTE, (REMOTE_TOP,), 1, 2, 9000)
            await shape(peers, POS, (TOP,), 1, 2, 0)
            send('setblock -270 79 -108 create:mechanical_pump[facing=east,waterlogged=false]')
            await shape(peers, POS, (TOP,), 1, 2, 9000)
            await shape(peers, REMOTE, (REMOTE_TOP,), 1, 2, 0)
            send('setblock -271 79 -109 air')
            print('PASS: both directions through upper ports preserve all 9000 mB', flush=True)

    reconnect = room / 'reconnect'
    reconnect.mkdir()
    async with server(args, room, port, 'restart') as (send, _):
        async with watch(args, reconnect, port, 'Builder', targets) as builder:
            build, _ = builder
            await shape((builder,), POS, (TOP,), 1, 2, 9000)
            await shape((builder,), CORNERS[0], CORNERS[1:], 2, 1)
            await shape((builder,), REMOTE, (REMOTE_TOP,), 1, 2, 0)
            await signal(build, 8)
            # Remove the controller, not the child. The child becomes a standalone 8000 mB tank.
            await eventually(lambda: build('state'), lambda state: bool(state.get('player'))
                             and state['player']['on_ground'], 'Builder settled after login')
            send(f'setblock {coords(POS)} air', 'setblock -269 79 -108 air')
            await state_on(build, (-269, 79, -108), 'minecraft:air')
            await shape((builder,), TOP, (), 1, 1, 8000)
            await signal(build, 15)
            send('clear Builder', f'give Builder {BUCKET} 8')
            await inventory_is(build, BUCKET, 8)
            for removed in range(1, 9):
                await click(build, BUCKET)
                await inventory_is(build, WATER, removed)
            await shape((builder,), TOP, (), 1, 1)
            send('clear Builder', f'give Builder {LAVA}', f'give Builder {WRENCH}')
            await inventory_is(build, LAVA, 1)
            await click(build, LAVA)
            await shape((builder,), TOP, (), 1, 1, 1000, 'minecraft:lava')
            await eventually(lambda: build(f'block {coords(TOP)}'),
                             lambda row: 'create_light=12' in row.get('state', ''), 'open lava tank luminance')
            await click(build, WRENCH)
            await shape((builder,), TOP, (), 1, 1, 1000, 'minecraft:lava', 0)
            await eventually(lambda: build(f'block {coords(TOP)}'),
                             lambda row: 'create_light=0' in row.get('state', ''), 'closed lava tank luminance')


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
    room = Path(tempfile.mkdtemp(prefix='create-multitank-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
