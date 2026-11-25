"""Place Create parts with real Horizon right-clicks on an isolated Pumpkin world."""
import argparse
import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile

from smoke_core import CONFIG, DATA, HERE, ROOT, Observation, proxy, server, until

SHAFT = 'create:shaft[axis=x,waterlogged=false]'
COG = 'create:cogwheel[axis=x,waterlogged=false]'
MOTOR = 'create:creative_motor[facing=east]'
SEED_SHAFT = (-262, 78, -110)


def coords(pos):
    return ' '.join(map(str, pos))


async def eventually(read, matches, why, seconds=20):
    result = None
    try:
        async with asyncio.timeout(seconds):
            while True:
                result = await read()
                if matches(result):
                    return result
                await asyncio.sleep(.15)
    except TimeoutError as exc:
        raise AssertionError(f'{why}: last result {result}') from exc


@asynccontextmanager
async def client(args, room, port, name, log_name='client.log'):
    instance = room / name
    instance.mkdir(exist_ok=True)
    endpoint = instance / 'control.json'
    logfile = instance / log_name
    (instance / 'horizon-mods.txt').write_text('mod.create:true\nmod.atlas:false\n')
    if args.create_jar:
        resources = instance / 'horizon-mods/create-resources'
        resources.mkdir(parents=True, exist_ok=True)
        installed = resources / args.create_jar.name
        if not installed.exists():
            shutil.copy2(args.create_jar, installed)
    with logfile.open('wb') as log, subprocess.Popen([
        str(args.client), '--name', name, '--resources', str(args.resources), '--game-dir', str(instance),
        '--home', str(instance), '--width', '1000', '--height', '620', '--render-distance', '4',
        '--quickPlayMultiplayer', f'127.0.0.1:{port}', '--offscreen', '--no-pause', '--control-socket', str(endpoint),
    ], cwd=instance, env=os.environ | {'APPDATA': str(room), 'LOCALAPPDATA': str(room),
        'CREATE_LAB_PLACEMENT_TRACE': '1', 'CREATE_HORIZON_TRACE': '1',
        'HORIZON_TELEMETRY_URL': 'off', 'HORIZON_NO_AUDIO': '1'},
        stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT) as game:
        try:
            await until(lambda: endpoint.is_file() or game.poll() is not None, f'{name} control ready',
                        getattr(args, 'startup_timeout', 180))
            assert game.poll() is None, logfile
            data = json.loads(endpoint.read_text())
            reader, writer = await asyncio.open_connection('127.0.0.1', data['port'])

            async def call(command):
                writer.write((command + '\n').encode())
                await writer.drain()
                reply = json.loads(await asyncio.wait_for(reader.readline(), 25))
                assert 'error' not in reply, (command.split()[0], reply)
                return reply

            try:
                await call('auth ' + data['token'])
                await eventually(lambda: call('state'), lambda r: r['screen'] == 'playing', f'{name} playing', 90)
                yield call, logfile
                await call('quit')
                assert await asyncio.to_thread(game.wait, 20) == 0, logfile
            finally:
                writer.close()
        finally:
            if game.poll() is None:
                game.kill()
                game.wait()
            endpoint.unlink(missing_ok=True)


async def state_on(call, pos, want):
    return await eventually(lambda: call(f'block {coords(pos)}'), lambda r: r.get('state') == want, f'{pos}: {want}')


async def aim(call, point, pos):
    await call(f'look-at {coords(point)}')
    hit = await call('looking-at')
    assert hit.get('kind') == 'block' and hit['block']['pos'] == list(pos), (point, pos, hit)
    return hit['block']


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    placements = {}
    sneaking = False

    def observe(number, body):
        nonlocal sneaking
        if number == 43:  # 26.3 PlayerInput
            sneaking = bool(body[0] & 32)

    async with server(args, room, port, 'placement') as (send, _):
        link = await asyncio.start_server(lambda r, w: proxy(r, w, port, Observation('Builder'), observe), '127.0.0.1', 0)
        async with link, client(args, room, link.sockets[0].getsockname()[1], 'Builder') as (build, log), client(args, room, port, 'Witness') as (see, _):
            for call in (build, see):
                await eventually(lambda: call(f'block {coords(SEED_SHAFT)}'), lambda r: r.get('loaded'), 'spawn chunk received')
            # Let Pumpkin receive the initial teleport confirmation before issuing another teleport.
            await asyncio.sleep(2)
            send('time set noon', 'fill -267 77 -114 -252 77 -103 stone',
                 'fill -267 78 -114 -252 81 -103 air', f'setblock {coords(SEED_SHAFT)} {SHAFT}',
                 'tp Builder -262.5 78 -107.1',
                 'give Builder create:creative_motor 4', 'give Builder create:shaft 8', 'give Builder create:cogwheel 8')
            for call in (build, see):
                await state_on(call, SEED_SHAFT, SHAFT)
            if args.create_jar:
                await until(lambda: '1372 local resources' in log.read_text(errors='replace'), 'original Create assets loaded')

            async def place(pos, want, sneak=False):
                if sneak:
                    await build('key shift down')
                    try:
                        await until(lambda: sneaking, 'Shift reached the server', 8)
                        await build('interact -262 78 -110 south')
                    finally:
                        await build('key shift up')
                else:
                    await build('use-item')
                for call in (build, see):
                    await state_on(call, pos, want)
                placements[pos] = want
                print(f'PASS: both clients received {want} at {pos}', flush=True)

            await build('select create:creative_motor')
            await aim(build, (-262.5, 77.99, -109.5), (-263, 77, -110))
            await place((-263, 78, -110), MOTOR)

            await build('select create:shaft')
            hit = await aim(build, (-261.24, 78.5, -109.5), SEED_SHAFT)
            assert hit['face'] != 'east', hit  # a vanilla click would not land at the extension
            await until(lambda: '[-262, 78, -110] -> [-261, 78, -110]' in log.read_text(errors='replace'),
                        'shaft preview targets the assisted cell', 12)
            await asyncio.sleep(.65)
            await build(f'screenshot {(room / "shaft-preview.png").as_posix()}')
            assert (room / 'shaft-preview.png').stat().st_size > 0
            await place((-261, 78, -110), SHAFT)

            await build('select create:cogwheel')
            send('tp Builder -260.9 78 -107.1')
            await eventually(lambda: build('state'), lambda r: abs(r['player']['position'][0] + 260.9) < .2, 'Builder moved')
            await aim(build, (-260.24, 78.5, -109.5), (-261, 78, -110))
            await place((-260, 78, -110), COG)
            await aim(build, (-259.5, 78.5, -109.5), (-260, 78, -110))
            await until(lambda: '[-260, 78, -110] -> [-260, 78, -109]' in log.read_text(errors='replace'),
                        'small cog preview targets the adjacent mesh cell', 12)
            await asyncio.sleep(.65)
            await build(f'screenshot {(room / "cog-preview.png").as_posix()}')
            await place((-260, 78, -109), COG)

            await build('select create:shaft')
            send('tp Builder -261.4 78 -107.1')
            await eventually(lambda: build('state'), lambda r: abs(r['player']['position'][0] + 261.4) < .2, 'Builder moved back')
            await build('wait 30')  # Allow the teleport's chunk/light stream to settle before testing input.
            hit = await aim(build, (-261.24, 78.15, -109.8), SEED_SHAFT)
            assert hit['face'] == 'south', hit
            await place((-262, 78, -109), 'create:shaft[axis=z,waterlogged=false]', sneak=True)

            send(f'setblock -256 78 -110 {SHAFT}', 'setblock -255 78 -110 stone',
                 'gamemode survival Builder', 'tp Builder -256.5 78 -107.1')
            await state_on(build, (-255, 78, -110), 'minecraft:stone')
            before = await eventually(lambda: build('state'), lambda r: r['gamemode'] == 'survival'
                                      and abs(r['player']['position'][0] + 256.5) < .2, 'Builder ready in survival')
            count = before['held']['count']
            hit = await aim(build, (-255.22, 78.5, -109.5), (-256, 78, -110))
            assert hit['point'][0] > -255.5, hit
            await place((-257, 78, -110), SHAFT)
            await eventually(lambda: build('state'), lambda r: r['held']['count'] == count - 1,
                             'blocked end fell back to the other end and consumed exactly one shaft')
            await state_on(see, (-255, 78, -110), 'minecraft:stone')
            print('PASS: blocked end fell back; exactly one shaft consumed in survival', flush=True)

    async with server(args, room, port, 'restart') as (send, _):
        async with client(args, room, port, 'AfterRestart') as (after, _):
            for pos, state in placements.items():
                await state_on(after, pos, state)
            print(f'PASS: all {len(placements)} player-placed states reloaded after restart', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', type=Path, default=ROOT / 'research_create_rust/.create-lab-build/game-target/fast/horizon-client.exe')
    parser.add_argument('--pumpkin', type=Path, default=HERE.parent / '.cache/core-target/debug/pumpkin.exe')
    parser.add_argument('--resources', type=Path, default=DATA / 'resources-create-v4')
    parser.add_argument('--create-jar', type=Path, help='optional, locally obtained Create 6.0.10 asset source')
    args = parser.parse_args()
    for attr in ('client', 'pumpkin', 'resources', 'create_jar'):
        if path := getattr(args, attr):
            setattr(args, attr, path.resolve(strict=True))
    room = Path(tempfile.mkdtemp(prefix='create-placement-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
