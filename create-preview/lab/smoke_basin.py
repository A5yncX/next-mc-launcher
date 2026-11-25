"""Drive basin mixing and compacting with real Create clients and vanilla inventories."""
import argparse
import asyncio
from pathlib import Path
import socket
import tempfile

from generate_pumpkin_data import CLIENT, read_json
from smoke_chute import watch
from smoke_depot import inventory_is
from smoke_core import CONFIG, DATA, HERE, ROOT, server, until
from smoke_placement import aim, coords, eventually, state_on

MIXER, MIX_BASIN, BURNER = (-268, 80, -108), (-268, 78, -108), (-268, 77, -108)
PRESS, PRESS_BASIN = (-263, 80, -108), (-263, 78, -108)
FEED_MIX, FEED_PRESS = (-268, 78, -109), (-263, 78, -109)
BASIN = 'create:basin[facing=down]'
COLD = 'create:blaze_burner[blaze=smouldering,facing=north]'
HOT = 'create:blaze_burner[blaze=kindled,facing=north]'


def items(observer, pos, field):
    tag = observer.tags.get(pos, {})
    return {entry['id']: entry['count'] for entry in tag.get(field, {}).get('Items', [])}


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    names = read_json(CLIENT / 'registries.json')['minecraft:block_entity_type']['entries']
    targets = {pos: (name, names[name]['protocol_id']) for pos, name in (
        (MIXER, 'create:mechanical_mixer'), (MIX_BASIN, 'create:basin'),
        (PRESS, 'create:mechanical_press'), (PRESS_BASIN, 'create:basin'),
    )}
    wanted = {MIX_BASIN: {'create:brass_ingot': 2, 'create:andesite_alloy': 2},
              PRESS_BASIN: {'minecraft:ice': 1}}

    async with server(args, room, port, 'basin') as (send, _):
        async with watch(args, room, port, 'Builder', targets) as (build, first), \
                watch(args, room, port, 'Witness', targets) as (see, second):
            peers = (first, second)
            await asyncio.sleep(2)
            send('fill -272 76 -112 -260 76 -104 stone',
                 'fill -272 77 -112 -260 82 -104 air',
                 *(f'setblock {coords(pos)} {BASIN}' for pos in (MIX_BASIN, PRESS_BASIN)),
                 f'setblock {coords(MIXER)} create:mechanical_mixer',
                 f'setblock {coords(PRESS)} create:mechanical_press[facing=east]',
                 'setblock -269 80 -108 create:cogwheel[axis=y,waterlogged=false]',
                 'setblock -269 79 -108 create:creative_motor[facing=up]',
                 'setblock -264 80 -108 create:creative_motor[facing=east]',
                 *(f'setblock {coords(pos)} minecraft:hopper[facing=south,enabled=true]' for pos in (FEED_MIX, FEED_PRESS)),
                 f'setblock {coords(BURNER)} {COLD}',
                 f'item replace block {coords(FEED_MIX)} container.0 with minecraft:copper_ingot 1',
                 f'item replace block {coords(FEED_MIX)} container.1 with create:zinc_ingot 1',
                 f'item replace block {coords(FEED_PRESS)} container.0 with minecraft:snow_block 9',
                 'tp Builder -267.5 77 -105.5', 'gamemode survival Builder', 'give Builder minecraft:coal 1')
            for call in (build, see):
                await state_on(call, MIX_BASIN, BASIN)
                await state_on(call, PRESS_BASIN, BASIN)
            await until(lambda: all(abs(o.tags.get(MIXER, {}).get('Speed', 0)) == 32
                                    and abs(o.tags.get(PRESS, {}).get('Speed', 0)) == 32 for o in peers),
                        'both clients see mixer and press driven at 32 RPM', 25)
            await until(lambda: all(items(o, PRESS_BASIN, 'OutputItems') == wanted[PRESS_BASIN]
                                    and o.tags.get(PRESS, {}).get('Mode') == 2 for o in peers),
                        'press in basin mode compacts nine snow blocks to one ice', 25)
            assert all(o.tags[MIXER].get('Running') == 0 and not items(o, MIX_BASIN, 'OutputItems') for o in peers)
            await eventually(lambda: build('state'), lambda r: r.get('player') and
                             abs(r['player']['position'][2] + 105.5) < .25, 'Builder near burner')
            await inventory_is(build, 'minecraft:coal', 1)
            await build('select minecraft:coal')
            await aim(build, (-267.5, 77.45, -107.55), BURNER)
            await build('use-item')
            await state_on(see, BURNER, HOT)
            await inventory_is(build, 'minecraft:coal', 0)
            await until(lambda: all(items(o, MIX_BASIN, 'OutputItems') == {'create:brass_ingot': 2} for o in peers),
                        'hot basin converts exactly one copper and zinc into two brass', 25)
            send(f'item replace block {coords(FEED_MIX)} container.0 with minecraft:andesite 2',
                 f'item replace block {coords(FEED_MIX)} container.1 with minecraft:iron_nugget 1',
                 f'item replace block {coords(FEED_MIX)} container.2 with create:zinc_nugget 1')
            await until(lambda: all(items(o, MIX_BASIN, 'OutputItems') == wanted[MIX_BASIN] for o in peers),
                        'both item-only alloy mixing recipes run from the hopper', 25)
            assert all(not items(o, pos, 'InputItems') for pos in wanted for o in peers)

    reconnect = room / 'reconnect'
    reconnect.mkdir()
    async with server(args, room, port, 'restart') as (_, __):
        async with watch(args, reconnect, port, 'Builder', targets) as (build, observed):
            await state_on(build, MIX_BASIN, BASIN)
            await until(lambda: all(items(observed, pos, 'OutputItems') == expected for pos, expected in wanted.items()),
                        'both basin inventories restore exact item counts after restart', 20)
    print('PASS: cold and hot mixing, compacting, hopper feed and exact output after restart', flush=True)


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
    room = Path(tempfile.mkdtemp(prefix='create-basin-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
