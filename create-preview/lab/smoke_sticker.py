"""Verify sticker placement into power, rising-edge latch, and reload on real clients."""
import argparse
import asyncio
from pathlib import Path
import socket
import tempfile

from smoke_core import CONFIG, DATA, HERE, ROOT, server
from smoke_depot import inventory_is
from smoke_placement import aim, client, coords, eventually, state_on

STICKER = 'create:sticker'
POS, SUPPORT, POWER = (-268, 78, -108), (-268, 78, -109), (-269, 78, -108)


def state(extended, powered):
    return f'{STICKER}[extended={str(extended).lower()},facing=south,powered={str(powered).lower()}]'


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    async with server(args, room, port, 'sticker') as (send, _):
        async with client(args, room, port, 'Builder') as (build, _), \
                client(args, room, port, 'Witness') as (see, _):
            await asyncio.sleep(2)
            send('fill -273 77 -112 -260 77 -102 stone', 'fill -273 78 -112 -260 82 -102 air')
            await asyncio.sleep(1)
            send(f'setblock {coords(SUPPORT)} stone', f'setblock {coords(POWER)} redstone_block',
                 'tp Builder -267.5 78 -104.5 facing -267.5 78.55 -108.5',
                 'gamemode survival Builder', f'give Builder {STICKER} 1')
            await eventually(lambda: build('state'), lambda row: row.get('player')
                             and abs(row['player']['position'][2] + 104.5) < .25, 'Builder at sticker fixture')
            await inventory_is(build, STICKER, 1)
            await state_on(see, POWER, 'minecraft:redstone_block')
            await build(f'select {STICKER}')
            await aim(build, (-267.5, 78.55, -108.5), SUPPORT)
            await asyncio.sleep(.5)
            await build('use-item')
            for call in (build, see):
                await state_on(call, POS, state(False, True))
            await inventory_is(build, STICKER, 0)
            print('PASS: placed facing south into existing power without toggling', flush=True)

            for powered, extended in ((False, False), (True, True), (False, True), (True, False),
                                      (False, False), (True, True)):
                send(f'setblock {coords(POWER)} ' + ('redstone_block' if powered else 'air'))
                for call in (build, see):
                    await state_on(call, POS, state(extended, powered))
            print('PASS: only rising edges toggle on both clients', flush=True)

    reconnect = room / 'reconnect'
    reconnect.mkdir()
    async with server(args, room, port, 'restart') as (send, _):
        async with client(args, reconnect, port, 'Builder') as (build, _):
            await state_on(build, POS, state(True, True))
            send(f'setblock {coords(POWER)} air')
            await state_on(build, POS, state(True, False))
            send(f'setblock {coords(POWER)} redstone_block')
            await state_on(build, POS, state(False, True))
            print('PASS: extended latch survives reload and responds to new signal', flush=True)


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
    room = Path(tempfile.mkdtemp(prefix='create-sticker-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
