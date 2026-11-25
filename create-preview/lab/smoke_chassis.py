"""Two real Horizon clients: chassis placement, glue, and restart."""
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
from smoke_placement import aim, coords, eventually, state_on

LINEAR, SECONDARY, RADIAL = (f'create:{name}_chassis' for name in ('linear', 'secondary_linear', 'radial'))
POS, SUPPORT, SECOND, ROUND = (-268, 78, -108), (-268, 78, -109), (-266, 78, -108), (-264, 78, -108)


def linear(name=LINEAR, top=False, bottom=False):
    return f'{name}[axis=z,sticky_bottom={str(bottom).lower()},sticky_top={str(top).lower()}]'


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    ids = create_ids(read_json(CLIENT / 'registries.json'), 'block_entity_type')
    targets = {pos: (name, ids[name]) for pos, name in ((POS, LINEAR), (SECOND, SECONDARY), (ROUND, RADIAL))}
    round_state = f'{RADIAL}[axis=y,sticky_east=false,sticky_north=false,sticky_south=false,sticky_west=false]'
    async with server(args, room, port, 'chassis') as (send, _):
        async with watch(args, room, port, 'Builder', targets) as (build, a), \
                watch(args, room, port, 'Witness', targets) as (see, b):
            await asyncio.sleep(2)
            send('fill -273 77 -112 -260 77 -102 stone', 'fill -273 78 -112 -260 82 -102 air')
            await asyncio.sleep(1)
            send(f'setblock {coords(SUPPORT)} stone', f'setblock {coords(SECOND)} {linear(SECONDARY)}',
                 f'setblock {coords(ROUND)} {round_state}', 'tp Builder -267.5 78 -104.5',
                 'gamemode survival Builder', f'give Builder {LINEAR} 1', 'give Builder minecraft:slime_ball 2')
            await state_on(see, SUPPORT, 'minecraft:stone')
            await eventually(lambda: build('state'), lambda r: r.get('player') and
                             abs(r['player']['position'][2] + 104.5) < .25, 'Builder at fixture')
            await inventory_is(build, LINEAR, 1)
            await build(f'select {LINEAR}')
            await aim(build, (-267.5, 78.55, -108.5), SUPPORT)
            await build('use-item')
            for call in (build, see):
                await state_on(call, POS, linear())
            await inventory_is(build, LINEAR, 0)
            await until(lambda: all(o.tags.get(pos, {}).get('ScrollValue') == 8 for o in (a, b) for pos in targets),
                        'all three chassis types have the default range on both clients')

            await build('select minecraft:slime_ball')
            hit = await aim(build, (-267.5, 78.55, -107.5), POS)
            assert hit['face'] == 'south', hit
            for state in (linear(top=True), linear(top=True, bottom=True)):
                await build('use-item')
                for call in (build, see):
                    await state_on(call, POS, state)
            await inventory_is(build, 'minecraft:slime_ball', 2)
            print('PASS: apply glue to one face, repeat to fill the other, keep held slime', flush=True)

            send('clear Builder')
            await inventory_is(build, 'minecraft:slime_ball', 0)
            await build('key shift down')
            try:
                await build('wait 4')
                await build('use-item')
                for call in (build, see):
                    await state_on(call, POS, linear(bottom=True))
            finally:
                await build('key shift up')
            print('PASS: empty-hand sneak clears only the clicked face', flush=True)

    reconnect = room / 'reconnect'
    reconnect.mkdir()
    async with server(args, room, port, 'restart') as (_, __):
        async with watch(args, reconnect, port, 'Builder', targets) as (build, obs):
            await state_on(build, POS, linear(bottom=True))
            await state_on(build, SECOND, linear(SECONDARY))
            await state_on(build, ROUND, round_state)
            await until(lambda: all(obs.tags.get(pos, {}).get('ScrollValue') == 8 for pos in targets),
                        'glue and the three stored ranges survive restart')


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
    room = Path(tempfile.mkdtemp(prefix='create-chassis-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
