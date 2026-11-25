"""Live survival funnel tests with two Horizon clients and authoritative inventories."""
import argparse
import asyncio
from pathlib import Path
import socket
import tempfile

from generate_pumpkin_data import CLIENT, read_json
from smoke_chute import check_chests, watch
from smoke_core import CONFIG, DATA, HERE, ROOT, server, until
from smoke_depot import inventory_is
from smoke_placement import aim, coords, eventually, state_on

ANDESITE = (-268, 78, -108)
BRASS = (-264, 78, -108)
POWER = (-263, 78, -108)
WRENCH = 'create:wrench'


def below(p):
    return p[0], p[1] - 1, p[2]


def above(p):
    return p[0], p[1] + 1, p[2]


def name(p):
    return 'create:andesite_funnel' if p == ANDESITE else 'create:brass_funnel'


def state(p, extracting=True, powered=False):
    return f'{name(p)}[extracting={str(extracting).lower()},facing=up,powered={str(powered).lower()},waterlogged=false]'


async def move(build, send, p):
    send(f'tp Builder {coords(p)}')
    await eventually(lambda: build('state'), lambda r: r.get('player') and all(
        abs(a - b) < .2 for a, b in zip(r['player']['position'], p)), 'Builder in range')


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    registry = read_json(CLIENT / 'registries.json')['minecraft:block_entity_type']['entries']
    targets = {p: (name(p), registry[name(p)]['protocol_id']) for p in (ANDESITE, BRASS)}
    async with server(args, room, port, 'funnel') as (send, _):
        async with watch(args, room, port, 'Builder', targets) as (build, first), \
                watch(args, room, port, 'Witness', targets) as (see, second):
            await asyncio.sleep(2)
            send('fill -272 76 -112 -260 76 -104 stone', 'fill -272 77 -112 -260 82 -104 air',
                 *(f'setblock {coords(below(p))} minecraft:stone' for p in (ANDESITE, BRASS)),
                 'setblock -268 78 -106 stone', 'setblock -264 78 -106 stone',
                 f'setblock {coords(POWER)} minecraft:redstone_block',
                 'gamemode survival Builder', 'give Builder create:andesite_funnel 1',
                 'give Builder create:brass_funnel 1', f'give Builder {WRENCH} 1',
                 'give Builder minecraft:stone 7', 'give Builder minecraft:dirt 1')
            for p in (ANDESITE, BRASS):
                x, y, z = p
                await move(build, send, (x + .5, y + 1, z + 2.5))
                hit = await aim(build, (x + .5, y - .125, z + .5), below(p))
                assert hit['face'] == 'up', hit
                await build(f'select {name(p)}')
                await build('use-item')
                for call in (build, see):
                    await state_on(call, p, state(p, powered=p == BRASS))
                await inventory_is(build, name(p), 0)
            print('PASS: real survival placement for both funnel variants', flush=True)
            send(*(f'setblock {coords(below(p))} minecraft:chest' for p in (ANDESITE, BRASS)))

            x, y, z = ANDESITE
            await move(build, send, (x + .5, y + 1, z + 2.5))
            await aim(build, (x + .5, y + .6, z + .5), ANDESITE)
            await build(f'select {WRENCH}')
            await build('use-item')
            await state_on(see, ANDESITE, state(ANDESITE, extracting=False))
            hit = await aim(build, (x + .5, y + .6, z + .5), ANDESITE)
            assert hit['face'] == 'up', hit
            await build('select minecraft:stone')
            await build('use-item')
            await inventory_is(build, 'minecraft:stone', 0)
            log = room / 'funnel.log'
            await check_chests(send, log, {below(ANDESITE): 7}, 'seven held stone insert into lower chest')
            await build(f'select {WRENCH}')
            await build('use-item')
            for call in (build, see):
                await state_on(call, ANDESITE, state(ANDESITE))
            send(f'setblock {coords(above(ANDESITE))} minecraft:chest')
            await asyncio.sleep(4)
            await check_chests(send, log, {below(ANDESITE): 0, above(ANDESITE): 7}, 'andesite transfers seven items exactly')

            x, y, z = BRASS
            await move(build, send, (x + .5, y - 1, z + 1.4))
            hit = await aim(build, (x + .5, y + .14, z + .915), BRASS)
            assert hit['face'] == 'south', hit
            await build('select minecraft:dirt')
            await asyncio.sleep(.15)
            await build('use-item')
            filter_is_dirt = lambda o: o.tags.get(BRASS, {}).get('Filter', {}).get('id') in ('dirt', 'minecraft:dirt')
            await until(lambda: all(filter_is_dirt(o) for o in (first, second)), 'both clients see brass dirt filter', 10)
            await inventory_is(build, 'minecraft:dirt', 1)
            send(f'setblock {coords(above(BRASS))} minecraft:chest',
                 f'item replace block {coords(below(BRASS))} container.0 with minecraft:stone 5',
                 f'item replace block {coords(below(BRASS))} container.1 with minecraft:dirt 4')
            await asyncio.sleep(1)
            await check_chests(send, log, {below(BRASS): 9, above(BRASS): 0}, 'redstone blocks both stacks')
            send(f'setblock {coords(POWER)} minecraft:air')
            await state_on(see, BRASS, state(BRASS))
            await asyncio.sleep(2)
            await check_chests(send, log, {below(BRASS): 5, above(BRASS): 4}, 'brass moves only four matching dirt')

    reconnect = room / 'reconnect'
    reconnect.mkdir()
    async with server(args, room, port, 'restart') as (send, _):
        async with watch(args, reconnect, port, 'Builder', targets) as (build, observation):
            await state_on(build, ANDESITE, state(ANDESITE))
            await state_on(build, BRASS, state(BRASS))
            await until(lambda: filter_is_dirt(observation), 'brass filter survives restart', 10)
            await check_chests(send, room / 'restart.log', {below(ANDESITE): 0, above(ANDESITE): 7,
                               below(BRASS): 5, above(BRASS): 4}, 'all moved items survive restart')


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
    room = Path(tempfile.mkdtemp(prefix='create-funnel-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
