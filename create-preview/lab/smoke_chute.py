"""Verify normal/smart chute transfers with two live Horizon clients.

Use the integrated lab binary. Chest inventory contents are inspected on the server;
the client proxy observes both chutes and must agree on their states.
"""
import argparse
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import re
import socket
import tempfile

from generate_pumpkin_data import CLIENT, read_json
from smoke_core import CONFIG, DATA, HERE, ROOT, Observation, proxy, server, until
from smoke_placement import client, coords, state_on

NORMAL_SOURCE, NORMAL_CHUTE, NORMAL_TARGET = (-268, 79, -108), (-268, 78, -108), (-268, 77, -108)
SMART_SOURCE, SMART_CHUTE, SMART_TARGET = (-264, 79, -108), (-264, 78, -108), (-264, 77, -108)
SMART_POWER = (-263, 78, -108)
NORMAL_STATE = 'create:chute[facing=down,shape=normal,waterlogged=false]'
SMART_STATE = 'create:smart_chute[powered=false]'


async def check_chests(send, log_path, expected, label):
    offset = log_path.stat().st_size
    send(*(f'data get block {coords(pos)} Items' for pos in expected))

    def satisfied():
        entries = {}
        for line in log_path.read_bytes()[offset:].decode(errors='replace').splitlines():
            for pos in expected:
                prefix = f'{pos[0]}, {pos[1]}, {pos[2]}'
                marker = ' has the following block data: '
                if line.startswith(prefix) and marker in line:
                    contents = line.rsplit(marker, 1)[1]
                    entries[pos] = sum(map(int, re.findall(r'\bcount:\s*(\d+)', contents)))
        if set(entries) == set(expected) and entries != expected:
            raise AssertionError((expected, entries, log_path))
        return entries == expected

    await until(satisfied, label, 10)


@asynccontextmanager
async def watch(args, room, port, name, targets):
    observation = Observation(name, targets)
    link = await asyncio.start_server(lambda reader, writer: proxy(reader, writer, port, observation), '127.0.0.1', 0)
    async with link, client(args, room, link.sockets[0].getsockname()[1], name) as (call, _):
        yield call, observation
        assert observation.error is None, observation.error


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    registry = read_json(CLIENT / 'registries.json')['minecraft:block_entity_type']['entries']
    resources = [
        (NORMAL_SOURCE, 'minecraft:chest'), (NORMAL_CHUTE, 'create:chute'),
        (NORMAL_TARGET, 'minecraft:chest'), (SMART_SOURCE, 'minecraft:chest'),
        (SMART_CHUTE, 'create:smart_chute'), (SMART_TARGET, 'minecraft:chest'),
    ]
    targets = {pos: (name, registry[name]['protocol_id']) for pos, name in resources}

    log = room / 'chute.log'
    async with server(args, room, port, 'chute') as (send, _):
        async with watch(args, room, port, 'Builder', targets) as (build, first), \
                watch(args, room, port, 'Witness', targets) as (see, second):
            observers = (first, second)
            await asyncio.sleep(2)
            send('fill -272 76 -112 -260 76 -104 stone',
                 'fill -272 77 -112 -260 82 -104 air',
                 *(f'setblock {coords(pos)} minecraft:chest' for pos, _ in resources if pos not in (NORMAL_CHUTE, NORMAL_TARGET, SMART_CHUTE)),
                 f'setblock {coords(NORMAL_TARGET)} minecraft:stone',
                 f'setblock {coords(NORMAL_CHUTE)} {NORMAL_STATE}',
                 f'item replace block {coords(NORMAL_SOURCE)} container.0 with minecraft:stone 20')
            for call in (build, see):
                await state_on(call, NORMAL_CHUTE, NORMAL_STATE)
            await until(lambda: all(o.tags.get(NORMAL_CHUTE, {}).get('ItemPosition') == 0.5
                                    and o.tags[NORMAL_CHUTE].get('Item', {}).get('count') == 16
                                    for o in observers), 'both clients see 16 items wait at the blocked midpoint', 10)
            await check_chests(send, log, {NORMAL_SOURCE: 4}, 'blocked chute leaves four stone at the source')
            send(f'setblock {coords(NORMAL_TARGET)} minecraft:chest')
            await asyncio.sleep(2)
            await check_chests(send, log, {NORMAL_SOURCE: 0, NORMAL_TARGET: 20}, 'normal chute moved exactly 20 stone')

            send(f'setblock {coords(SMART_CHUTE)} {SMART_STATE}',
                 f'item replace block {coords(SMART_SOURCE)} container.0 with minecraft:stone 5')
            for call in (build, see):
                await state_on(call, SMART_CHUTE, SMART_STATE)
            await asyncio.sleep(2)
            await check_chests(send, log, {SMART_SOURCE: 0, SMART_TARGET: 5}, 'unpowered smart chute moved five stone')

            send(f'setblock {coords(SMART_POWER)} minecraft:redstone_block')
            for call in (build, see):
                await state_on(call, SMART_CHUTE, 'create:smart_chute[powered=true]')
            send(f'item replace block {coords(SMART_SOURCE)} container.1 with minecraft:stone 5')
            await asyncio.sleep(2)
            await check_chests(send, log, {SMART_SOURCE: 5, SMART_TARGET: 5}, 'powered smart chute leaves both inventories unchanged')
            send(f'setblock {coords(SMART_POWER)} minecraft:air')
            for call in (build, see):
                await state_on(call, SMART_CHUTE, SMART_STATE)
            await asyncio.sleep(2)
            await check_chests(send, log, {SMART_SOURCE: 0, SMART_TARGET: 10}, 'smart chute resumes with all stone conserved')
            for observer in observers:
                assert observer.tags.get(NORMAL_CHUTE), observer.name
                assert observer.tags.get(SMART_CHUTE), observer.name

    reconnect = room / 'reconnect'
    reconnect.mkdir()
    async with server(args, room, port, 'restart') as (send, _):
        async with watch(args, reconnect, port, 'Builder', targets) as (build, _):
            await state_on(build, NORMAL_CHUTE, NORMAL_STATE)
            await state_on(build, SMART_CHUTE, SMART_STATE)
            await check_chests(send, room / 'restart.log', {NORMAL_TARGET: 20, SMART_TARGET: 10}, 'destination chest contents survive restart')


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
    room = Path(tempfile.mkdtemp(prefix='create-chute-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
