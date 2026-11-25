"""Two real clients verify placed blaze cages, fuel, heat and durable state."""
import argparse
import asyncio
from pathlib import Path
import socket
import tempfile

from generate_full_registry import create_ids
from generate_passive_data import generate
from generate_pumpkin_data import CLIENT, read_json
from smoke_core import CONFIG, DATA, HERE, ROOT, server, until
from smoke_depot import inventory_is
from smoke_drivetrain import watch
from smoke_placement import aim, coords, eventually, state_on

BURNER, EMPTY, LIT, CAKE, CREATIVE, GOGGLES = (
    f'create:{name}' for name in ('blaze_burner', 'empty_blaze_burner', 'lit_blaze_burner',
                                  'blaze_cake', 'creative_blaze_cake', 'goggles')
)
HOT, COLD, WIRE = (-268, 78, -108), (-265, 78, -108), (-268, 78, -110)


def burner(heat, facing='south'):
    return f'{BURNER}[blaze={heat},facing={facing}]'


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    be_id = create_ids(read_json(CLIENT / 'registries.json'), 'block_entity_type')[BURNER]
    targets = {pos: (BURNER, be_id) for pos in (HOT, COLD)}
    generate(room / 'create-lab/datapacks/create-passive')

    async with server(args, room, port, 'burner') as (send, _):
        send('datapack enable "file/create-passive"')
        async with watch(args, room, port, 'Builder', targets) as (build, a), \
                watch(args, room, port, 'Witness', targets) as (see, b):
            await asyncio.sleep(2)
            send('fill -272 77 -113 -261 77 -104 stone', 'fill -272 78 -113 -261 82 -104 air',
                 'gamemode survival Builder', 'tp Builder -267.5 78 -105.5',
                 f'give Builder {BURNER} 1', f'give Builder {EMPTY} 1', 'give Builder minecraft:coal 2',
                 'give Builder minecraft:flint_and_steel 1', 'give Builder minecraft:soul_sand 1',
                 'give Builder minecraft:iron_shovel 1', f'give Builder {CAKE} 1',
                 f'give Builder {CREATIVE} 1', f'give Builder {GOGGLES} 1',
                 'setblock -268 78 -109 minecraft:comparator[facing=south]',
                 f'setblock {coords(WIRE)} minecraft:redstone_wire')
            await eventually(lambda: build('state'), lambda r: r.get('player') and
                             abs(r['player']['position'][2] + 105.5) < .25, 'Builder at fixture')

            async def click(item):
                await build(f'select {item}')
                await build('use-item')

            async def both(pos, state):
                for call in (see, build):
                    await state_on(call, pos, state)

            async def check(heat, level, comparator):
                await both(HOT, burner(heat))
                await until(lambda: all(o.tags.get(HOT, {}).get('fuelLevel') == level and
                                        o.tags[HOT]['burnTimeRemaining'] > 0 for o in (a, b)),
                            f'authoritative {heat} fuel for both clients')
                for call in (see, build):
                    await eventually(lambda: call(f'block {coords(WIRE)}'),
                                     lambda row: f'power={comparator},' in row.get('state', ''),
                                     f'redstone wire power {comparator}')

            for pos, item, heat in ((HOT, BURNER, 'smouldering'), (COLD, EMPTY, 'none')):
                if pos == COLD:
                    send('tp Builder -264.5 78 -105.5')
                    await eventually(lambda: build('state'), lambda r: r.get('player') and
                                     abs(r['player']['position'][0] + 264.5) < .25, 'Builder at empty cage')
                floor = (pos[0], 77, pos[2])
                await inventory_is(build, item, 1)
                await aim(build, (pos[0] + .5, 78.0, pos[2] + .5), floor)
                await click(item)
                await both(pos, burner(heat))
                await inventory_is(build, item, 0)
            assert not a.tags.get(COLD) and not b.tags.get(COLD)

            await aim(build, (-264.5, 78.45, -107.55), COLD)
            await click('minecraft:flint_and_steel')
            await both(COLD, f'{LIT}[flame_type=regular]')
            await click('minecraft:soul_sand')
            await both(COLD, f'{LIT}[flame_type=soul]')
            await inventory_is(build, 'minecraft:soul_sand', 1)
            await click('minecraft:iron_shovel')
            await both(COLD, burner('none', 'north'))
            assert not a.tags.get(COLD) and not b.tags.get(COLD)
            print('PASS: filled and empty survival placement; empty cage ignites, changes flame and extinguishes', flush=True)

            await aim(build, (-267.5, 78.45, -107.55), HOT)
            await click('minecraft:coal')
            await inventory_is(build, 'minecraft:coal', 1)
            await check('kindled', 1, 2)
            await click(CAKE)
            await inventory_is(build, CAKE, 0)
            await check('seething', 2, 3)
            await click('minecraft:coal')
            await inventory_is(build, 'minecraft:coal', 1)
            await click(GOGGLES)
            await until(lambda: all(o.tags.get(HOT, {}).get('Goggles') == 1 for o in (a, b)),
                        'goggles update on both clients')
            print('PASS: coal and cake consumption, rejection by hotter fuel, comparator and goggles', flush=True)

    reconnect = room / 'reconnect'
    reconnect.mkdir()
    async with server(args, room, port, 'restart') as (_, __):
        async with watch(args, reconnect, port, 'Builder', targets) as (build, a), \
                watch(args, reconnect, port, 'Witness', targets) as (see, b):
            await both(HOT, burner('seething'))
            await until(lambda: all(o.tags.get(HOT, {}).get('fuelLevel') == 2 and
                                    o.tags[HOT]['burnTimeRemaining'] > 0 and
                                    o.tags[HOT].get('Goggles') == 1 for o in (a, b)),
                        'remaining fuel and goggles retained after restart')
            await aim(build, (-267.5, 78.45, -107.55), HOT)
            await click(CREATIVE)
            await both(HOT, burner('smouldering'))
            await inventory_is(build, CREATIVE, 1)
            await until(lambda: all(o.tags.get(HOT, {}).get('isCreative') == 1 for o in (a, b)),
                        'creative fuel cycling broadcast')


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
    room = Path(tempfile.mkdtemp(prefix='create-burner-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
