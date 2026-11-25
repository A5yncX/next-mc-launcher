"""Exercise the patched Pumpkin using two real Horizon windows and loopback packet observations."""
import argparse
import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = ROOT / 'research_nextmc_release/.qa-beta2/profile/NextMC'
TARGETS = {(-263, 78, -110): (36349, 73), (-262, 78, -110): (37744, 138), (-261, 78, -110): (36344, 71)}
COG = tuple(TARGETS)[-1]
WORLD_FRAMES = 4800
CONFIG = '''seed = "101"
use_tty = false
spawn_protection = 0
default_gamemode = "Creative"
default_level_name = "create-lab"
[logging]
color = false
[networking.java]
address = "127.0.0.1:{port}"
online_mode = false
encryption = false
view_distance = 5
simulation_distance = 4
[networking.java.compression]
enabled = false
[networking.java.authentication]
enabled = false
[networking.bedrock]
enabled = false
[networking.bedrock.nethernet]
enabled = false
[networking.lan_broadcast]
enabled = false
[networking.management]
enabled = false
[networking.query]
enabled = false
[telemetry]
enabled = false
[update_checker]
enabled = false
[plugins]
enabled = false
'''


def varint(buf, pos=0):
    value = 0
    for i in range(5):
        byte = buf[pos + i]
        value |= (byte & 127) << (i * 7)
        if byte < 128:
            return value, pos + i + 1
    raise ValueError('invalid VarInt')


def signed(n, bits):
    return n - (1 << bits) if n >> (bits - 1) else n


def block_pos(raw):
    packed, = struct.unpack_from('>Q', raw)
    return signed(packed >> 38, 26), signed(packed & 4095, 12), signed((packed >> 12) & ((1 << 26) - 1), 26)


def palette(raw, offset, entries, indirect_bits):
    bits = raw[offset]
    offset += 1
    if bits == 0:
        single, offset = varint(raw, offset)
        return (lambda _index: single), offset
    values = None
    if bits <= indirect_bits:
        count, offset = varint(raw, offset)
        values = []
        for _ in range(count):
            value, offset = varint(raw, offset)
            values.append(value)
    per_long = 64 // bits

    def get(index):
        word, = struct.unpack_from('>Q', raw, offset + index // per_long * 8)
        value = (word >> ((index % per_long) * bits)) & ((1 << bits) - 1)
        return value if values is None else values[value]

    return get, offset + ((entries + per_long - 1) // per_long) * 8


def kinetic_tags(raw, offset=0):
    assert raw[offset] == 10
    return kinetic_compound(raw, offset + 1)


def kinetic_compound(raw, offset):
    fields = {}
    while raw[offset] != 0:
        kind, length = struct.unpack_from('>BH', raw, offset)
        offset += 3
        name = raw[offset:offset + length].decode()
        offset += length
        if kind == 10:
            fields[name], offset = kinetic_compound(raw, offset)
        elif kind == 9:
            element, count = struct.unpack_from('>Bi', raw, offset)
            offset += 5
            assert count >= 0 and (count == 0 or element == 10), (element, count)
            fields[name] = []
            for _ in range(count):
                entry, offset = kinetic_compound(raw, offset)
                fields[name].append(entry)
        elif kind == 11:
            count, = struct.unpack_from('>i', raw, offset)
            offset += 4
            assert count >= 0 and count <= (len(raw) - offset) // 4
            fields[name] = list(struct.unpack_from(f'>{count}i', raw, offset))
            offset += count * 4
        elif kind == 8:
            size, = struct.unpack_from('>H', raw, offset)
            offset += 2
            fields[name] = raw[offset:offset + size].decode()
            offset += size
        else:
            fmt = {1: '>b', 3: '>i', 5: '>f'}[kind]
            fields[name], = struct.unpack_from(fmt, raw, offset)
            offset += struct.calcsize(fmt)
    return fields, offset + 1


class Observation:
    def __init__(self, name, targets=TARGETS):
        self.name = name
        self.targets = targets
        x, _, z = next(iter(targets))
        self.chunk = x // 16, z // 16
        self.states = {}
        self.cracks = {}
        self.updates = []
        self.initial = {}
        self.motor_settings = {}
        self.tags = {}
        self.kinds = {71, 73, 138} | {kind for _, kind in targets.values()}
        self.chunk_states = {}
        self.play = False
        self.error = None

    def packet(self, number, raw):
        if number == 8:  # BlockUpdate
            pos = block_pos(raw)
            if pos in self.targets:
                self.states[pos] = varint(raw, 8)[0]
        elif number == 5:  # BlockDestruction
            _, offset = varint(raw)
            pos = block_pos(raw[offset:])
            if pos in self.targets:
                stage, = struct.unpack_from('b', raw, offset + 8)
                self.cracks.setdefault(pos, []).append(stage)
        elif number == 86:  # SectionBlocksUpdate
            packed, = struct.unpack_from('>Q', raw)
            x, y, z = signed(packed >> 42, 22), signed(packed & 0xfffff, 20), signed((packed >> 20) & 0x3fffff, 22)
            count, offset = varint(raw, 8)
            for _ in range(count):
                value, offset = varint(raw, offset)
                pos = (16 * x + ((value >> 8) & 15), 16 * y + (value & 15), 16 * z + ((value >> 4) & 15))
                if pos in self.targets:
                    self.states[pos] = value >> 12
        elif number == 6:  # BlockEntityData
            pos = block_pos(raw)
            if pos in self.targets:
                kind, offset = varint(raw, 8)
                tag, _ = kinetic_tags(raw, offset)
                self.updates.append((pos, kind, tag.get('Speed')))
                self.tags[pos] = tag
                if 'ScrollValue' in tag:
                    self.motor_settings[pos] = tag['ScrollValue']
        elif number == 46 and struct.unpack_from('>ii', raw) == self.chunk:
            # Only inspect the fixture chunk, in the lab's standard -64..319 overworld.
            count, offset = varint(raw, 8)
            for _ in range(count):
                _, offset = varint(raw, offset)
                size, offset = varint(raw, offset)
                offset += size * 8
            size, offset = varint(raw, offset)
            end = offset + size
            for bottom in range(-64, 320, 16):
                get, offset = palette(raw, offset + 4, 4096, 8)
                _, offset = palette(raw, offset, 64, 3)
                for pos in self.targets:
                    x, y, z = pos
                    if bottom <= y < bottom + 16:
                        self.chunk_states[pos] = get((y % 16) * 256 + (z % 16) * 16 + x % 16)
            assert offset == end, (offset, end)
            count, offset = varint(raw, end)
            for _ in range(count):
                xz, y = struct.unpack_from('>Bh', raw, offset)
                pos = (self.chunk[0] * 16 + (xz >> 4), y, self.chunk[1] * 16 + (xz & 15))
                kind, offset = varint(raw, offset + 3)
                if kind not in self.kinds:
                    # shortcut: fixtures contain lab BEs; unknown BEs need a full NBT reader.
                    return
                tag, offset = kinetic_tags(raw, offset)
                if pos in self.targets:
                    self.initial[pos] = (kind, tag.get('Speed'))
                    self.tags[pos] = tag
                    if 'ScrollValue' in tag:
                        self.motor_settings[pos] = tag['ScrollValue']


async def proxy(reader, writer, port, observation, client_packet=None):
    source, sink = await asyncio.open_connection('127.0.0.1', port)

    async def read_frame(stream):
        prefix = bytearray()
        for _ in range(5):
            prefix += await stream.readexactly(1)
            if prefix[-1] < 128:
                break
        length, _ = varint(prefix)
        assert 0 < length <= 8 * 1024 * 1024, length
        return prefix, await stream.readexactly(length)

    phase = 'login'

    async def upstream():
        try:
            while True:
                prefix, frame = await read_frame(reader)
                if phase == 'config' and frame.startswith(b'\x02\x16horizon:block_registry'):
                    print(f'{observation.name}: registry reply {frame[24:].hex()}', flush=True)
                if phase == 'play' and client_packet:
                    number, offset = varint(frame)
                    client_packet(number, frame[offset:])
                sink.writelines((prefix, frame))
                await sink.drain()
        except asyncio.IncompleteReadError:
            pass

    async def downstream():
        nonlocal phase
        try:
            while True:
                prefix, frame = await read_frame(source)
                number, offset = varint(frame)
                if phase == 'login' and number == 2:
                    phase = 'config'
                elif phase == 'config' and number == 3:
                    phase = 'play'
                    observation.play = True
                elif phase == 'play':
                    observation.packet(number, frame[offset:])
                writer.writelines((prefix, frame))
                await writer.drain()
        except asyncio.IncompleteReadError:
            pass

    tasks = [asyncio.create_task(run()) for run in (upstream, downstream)]
    try:
        _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for result in await asyncio.gather(*tasks, return_exceptions=True):
            if isinstance(result, Exception) and not isinstance(result, ConnectionError):
                observation.error = result
    finally:
        sink.close()
        writer.close()


async def until(predicate, label, timeout=120):
    try:
        async with asyncio.timeout(timeout):
            while not predicate():
                await asyncio.sleep(0.1)
    except TimeoutError as e:
        raise TimeoutError(label) from e
    print(f'PASS: {label}', flush=True)


@asynccontextmanager
async def server(args, folder, port, round_name):
    log_path = folder / f'{round_name}.log'
    with log_path.open('wb') as log, subprocess.Popen([str(args.pumpkin)], cwd=folder,
        stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT) as proc:
        def contains(text):
            return text in log_path.read_text(errors='replace')

        def send(*commands):
            proc.stdin.write(('\n'.join(commands) + '\n').encode())
            proc.stdin.flush()

        try:
            await until(lambda: contains('Server is now running') or proc.poll() is not None, f'{round_name} startup', 45)
            assert proc.poll() is None, log_path
            yield send, contains
        finally:
            if proc.poll() is None:
                try:
                    send('stop')
                    await asyncio.to_thread(proc.wait, 60)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
    assert proc.returncode == 0 and contains('The server has stopped.'), log_path


@asynccontextmanager
async def client(args, folder, port, name, enabled=True):
    instance = folder / name
    instance.mkdir()
    (instance / 'horizon-mods.txt').write_text(f'mod.create:{str(enabled).lower()}\nmod.atlas:false\n')
    observation = Observation(name)
    listener = await asyncio.start_server(lambda r, w: proxy(r, w, port, observation), '127.0.0.1', 0)
    proxy_port = listener.sockets[0].getsockname()[1]
    report = instance / 'client.json'
    with (instance / 'client.log').open('wb') as log, subprocess.Popen([
        str(args.client), '--name', name, '--resources', str(args.resources), '--game-dir', str(instance),
        '--home', str(instance), '--width', '880', '--height', '540', '--render-distance', '4',
        '--quickPlayMultiplayer', f'127.0.0.1:{proxy_port}', '--world-frames', str(WORLD_FRAMES), '--smoke-report', str(report),
    ], cwd=instance, env=os.environ | {'APPDATA': str(folder), 'LOCALAPPDATA': str(folder)},
        stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT) as game:
        try:
            yield observation
            if enabled:
                assert await asyncio.to_thread(game.wait, 140) == 0, instance
                data = json.loads(report.read_bytes())
                assert data['error'] is None and data['frames'] >= WORLD_FRAMES and data['chunks'] > 0, data
                print(f'PASS: {name} rendered {data["frames"]} frames / {data["chunks"]} chunks', flush=True)
        finally:
            if game.poll() is None:
                game.kill()
            listener.close()
            await listener.wait_closed()
    if observation.error:
        raise observation.error


async def test(args, folder):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (folder / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    place = ('setblock -263 78 -110 create:creative_motor[facing=east]',
             'setblock -262 78 -110 create:shaft[axis=x,waterlogged=false]',
             'setblock -261 78 -110 create:cogwheel[axis=x,waterlogged=false]')
    async with server(args, folder, port, 'first') as (send, contains):
        async with client(args, folder, port, 'NoCreate', enabled=False) as off:
            await until(lambda: (folder / 'NoCreate/client.log').exists() and
                'This lab requires the pinned Horizon client with Create enabled' in
                (folder / 'NoCreate/client.log').read_text(errors='replace'), 'disabled Create refused', 60)
            assert not off.play and not contains('NoCreate joined the game')
        async with client(args, folder, port, 'CreateOne') as one, client(args, folder, port, 'CreateTwo') as two:
            both = (one, two)
            await until(lambda: all(contains(f'{c.name} joined the game') for c in both), 'both clients joined')
            await asyncio.sleep(2)
            send(*place)
            try:
                await until(lambda: all(c.states == {pos: info[0] for pos, info in TARGETS.items()} and
                    (COG, 71, 32.0) in c.updates for c in both), 'both received exact Create states and 32 RPM', 15)
            except TimeoutError:
                for c in both:
                    print(c.name, c.states, c.updates, c.error, flush=True)
                raise
            for c in both:
                c.updates.clear()
            send('setblock -262 78 -110 minecraft:air')
            await until(lambda: all(c.states.get((-262, 78, -110)) == 0 and
                (COG, 71, 0.0) in c.updates for c in both), 'breaking the shaft sent 0 RPM to both', 15)
            for c in both:
                c.updates.clear()
            send(place[1])
            await until(lambda: all((COG, 71, 32.0) in c.updates for c in both), 'replacing the shaft restored 32 RPM', 15)
    async with server(args, folder, port, 'restart') as (send, contains):
        async with client(args, folder, port, 'CreateAgain') as client_after:
            await until(lambda: contains('CreateAgain joined the game'), 'client joined restarted world')
            await until(lambda: client_after.initial == {pos: (info[1], 32.0) for pos, info in TARGETS.items()},
                'restart chunk contained all three native block entities at 32 RPM', 30)
            assert client_after.chunk_states == {pos: info[0] for pos, info in TARGETS.items()}, client_after.chunk_states
            print('PASS: restart chunk preserved each exact block state', flush=True)
    print('PASS: both server runs shut down cleanly', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pumpkin', type=Path, default=HERE.parent / '.cache/core-target/debug/pumpkin.exe')
    parser.add_argument('--client', type=Path, default=DATA / 'components/create-atlas-beta.1/target/plain/release/horizon-client.exe')
    parser.add_argument('--resources', type=Path, default=DATA / 'resources-create-v4')
    args = parser.parse_args()
    for attr in ('pumpkin', 'client', 'resources'):
        setattr(args, attr, getattr(args, attr).resolve(strict=True))
    run = Path(tempfile.mkdtemp(prefix='create-core-', dir=HERE.parent / '.cache'))
    print(f'Logs: {run}', flush=True)
    asyncio.run(test(args, run))
