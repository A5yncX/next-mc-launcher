"""Check stationary Create piston, extension pole and rope pulley with two Horizon clients."""
import argparse
import asyncio
from pathlib import Path
import socket
import tempfile

from generate_full_registry import create_ids
from generate_pumpkin_data import CLIENT, read_json
from smoke_core import CONFIG, DATA, HERE, ROOT, server, until
from smoke_depot import inventory_is
from smoke_drivetrain import watch
from smoke_encasing import move
from smoke_placement import aim, coords, state_on

PISTON, PULLEY, POLE = (-269, 78, -110), (-264, 78, -110), (-269, 78, -109)
NORMAL = 'create:mechanical_piston[axis_along_first=true,facing=south,state=retracted]'
STICKY = NORMAL.replace('mechanical_piston', 'sticky_mechanical_piston')
ROTATED = STICKY.replace('first=true', 'first=false')
ROPE_PULLEY = 'create:rope_pulley[axis=x]'
EXTENSION = 'create:piston_extension_pole[facing=north,waterlogged=false]'


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    ids = create_ids(read_json(CLIENT / 'registries.json'), 'block_entity_type')
    targets = {p: (s, ids[s.split('[')[0]]) for p, s in [(PISTON, STICKY), (PULLEY, ROPE_PULLEY)]}

    async def verify(calls, state, speed):
        for call, observation in calls:
            await state_on(call, PISTON, state)
            await state_on(call, PULLEY, ROPE_PULLEY)
            await until(lambda: observation.tags.get(PISTON, {}).get('Speed') == speed
                        and observation.tags.get(PULLEY, {}).get('Speed') == 32,
                        f'{observation.name} stationary actuator RPM')

    async with server(args, room, port, 'actuators') as (send, _):
        async with watch(args, room, port, 'Builder', targets) as (build, one), \
                watch(args, room, port, 'Witness', targets) as (see, two):
            await asyncio.sleep(2)
            send('fill -272 77 -113 -261 77 -105 stone', 'fill -272 78 -113 -261 82 -105 air',
                 'setblock -269 78 -111 stone', 'setblock -264 78 -111 stone',
                 'setblock -270 78 -110 create:creative_motor[facing=east]',
                 'setblock -265 78 -110 create:creative_motor[facing=east]',
                 'gamemode survival Builder', 'give Builder create:mechanical_piston 1',
                 'give Builder create:rope_pulley 1', 'give Builder create:piston_extension_pole 1',
                 'give Builder create:wrench 1', 'give Builder minecraft:slime_ball 2')
            for pos, item in [(PISTON, 'create:mechanical_piston'), (PULLEY, 'create:rope_pulley')]:
                await inventory_is(build, item, 1)
                await move(build, send, (pos[0] + .5, 78, -106.5))
                backing = (pos[0], 78, -111)
                await aim(build, (pos[0] + .5, 78.60, -110.02), backing)
                await build(f'select {item}')
                await asyncio.sleep(.3)  # Let Horizon send the new view rotation before right click.
                await build('use-item')
                await state_on(see, pos, NORMAL if pos == PISTON else ROPE_PULLEY)
                await inventory_is(build, item, 0)
            await move(build, send, (-268.5, 78, -106.5))
            await aim(build, (-268.5, 78.58, -109.02), PISTON)
            await build('select minecraft:slime_ball')
            await build('use-item')
            await inventory_is(build, 'minecraft:slime_ball', 1)
            await verify(((build, one), (see, two)), STICKY, 32)
            await build('select create:wrench')
            await build('use-item')
            await verify(((build, one), (see, two)), ROTATED, 0)
            await build('use-item')
            await verify(((build, one), (see, two)), STICKY, 32)
            await build('select create:piston_extension_pole')
            await build('use-item')
            for call in (build, see):
                await state_on(call, POLE, EXTENSION)
            await inventory_is(build, 'create:piston_extension_pole', 0)
            print('PASS: two clients see survival placement, one-slime conversion, wrench shaft selection and 32/0/32 RPM', flush=True)
    reconnect = room / 'reconnect'
    reconnect.mkdir()
    async with server(args, room, port, 'restart'):
        async with watch(args, reconnect, port, 'Builder', targets) as (build, one):
            await verify(((build, one),), STICKY, 32)
            await state_on(build, POLE, EXTENSION)
            await inventory_is(build, 'minecraft:slime_ball', 1)
    print('PASS: sticky base, rope pulley, pole, power and one remaining slimeball persisted', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', type=Path, default=ROOT / 'research_create_rust/.create-lab-build/game-target/fast/horizon-client.exe')
    parser.add_argument('--pumpkin', type=Path, default=HERE.parent / '.cache/core-target/debug/pumpkin.exe')
    parser.add_argument('--resources', type=Path, default=DATA / 'resources-create-v4')
    parser.add_argument('--create-jar', type=Path)
    args = parser.parse_args()
    for attr, path in vars(args).items():
        if path is not None:
            setattr(args, attr, path.resolve(strict=True))
    room = Path(tempfile.mkdtemp(prefix='create-actuators-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
