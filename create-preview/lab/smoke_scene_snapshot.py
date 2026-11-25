"""Verify saved scene attachments arrive just after both centre and streamed chunks."""
import argparse
import asyncio
import io
from pathlib import Path
import socket
import struct
import sys
import tempfile
import zlib

from smoke_core import CONFIG, DATA, HERE, ROOT, proxy, server, until
from smoke_placement import client

sys.path.insert(0, str(ROOT / 'research_create_rust/.create-lab-build/stage/tools'))
from anvil_dump import read_named, read_tag

CHUNKS = {(-17, -7): 17, (-16, -7): 18}
KEYS = ('moving_structures', 'moving_structure_poses')
CHANNEL = b'horizon:attachment_sync'


def tag(kind, key, content):
    name = key.encode()
    return struct.pack('>BH', kind, len(name)) + name + content


def scene(generation):
    def entry(key, version):
        return tag(10, key, tag(3, 'Version', struct.pack('>i', version)) +
                   tag(4, 'Generation', struct.pack('>q', generation)) +
                   tag(9, 'Entries', b'\x00' * 5) + b'\x00')
    return tag(10, 'PumpkinCustomData', tag(10, 'create', tag(10, 'contraption_scene',
        entry(KEYS[0], 2) + entry(KEYS[1], 1) + tag(3, 'ServerOnly', b'\x00' * 4) + b'\x00') + b'\x00') + b'\x00')


def seed_region(room, x, z, generation):
    path = room / f'create-lab/dimensions/minecraft/overworld/region/r.{x // 32}.{z // 32}.mca'
    data = bytearray(path.read_bytes())
    slot = 4 * ((z % 32) * 32 + x % 32)
    start = int.from_bytes(data[slot:slot + 3], 'big') * 4096
    assert start >= 8192 and data[start + 4] == 2
    size, = struct.unpack_from('>I', data, start)
    raw = zlib.decompress(data[start + 5:start + 4 + size])
    old = read_named(raw)
    assert (old['xPos'], old['zPos']) == (x, z) and 'PumpkinCustomData' not in old and raw[-1:] == b'\x00'
    payload = b'\x02' + zlib.compress(raw[:-1] + scene(generation) + b'\x00')
    record = struct.pack('>I', len(payload)) + payload
    sectors = (len(record) + 4095) // 4096
    assert len(data) % 4096 == 0 and sectors <= 255
    data[slot:slot + 4] = (len(data) // 4096).to_bytes(3, 'big') + bytes([sectors])
    data.extend(record.ljust(sectors * 4096, b'\x00'))
    path.write_bytes(data)


class SceneObserver:
    def __init__(self, name):
        self.name, self.error = name, None
        self.play = self.batch = False
        self.previous = None
        self.seen = set()

    def packet(self, number, raw):
        if number in (11, 12):
            self.batch = number == 12
        if number != 24 or not raw.startswith(bytes([len(CHANNEL)]) + CHANNEL):
            self.previous = struct.unpack_from('>ii', raw) if number == 46 else None
            return
        stream = io.BytesIO(raw[1 + len(CHANNEL):])
        kind, x, z, replace, count = struct.unpack('>BiiBB', stream.read(11))
        assert self.batch and self.previous == (x, z) and (kind, replace, count) == (3, 1, 2)
        for key, version in zip(KEYS, (2, 1), strict=True):
            assert stream.read(7) == b'\x06create'
            size = stream.read(1)[0]
            assert stream.read(size).decode() == key
            assert stream.read(1) == b'\x0a'
            assert read_tag(stream, 10) == {'Version': version, 'Generation': ('l', CHUNKS[x, z]), 'Entries': []}
        assert not stream.read()
        self.seen.add((x, z))
        self.previous = None


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port) +
        '\n[world.chunk]\ntype = "anvil"\n[world.chunk.compression]\nalgorithm = "ZLib"\nlevel = 6\n')
    async with server(args, room, port, 'seed'):
        async with client(args, room, port, 'Seeder'):
            await asyncio.sleep(3)
    for pos, generation in CHUNKS.items():
        seed_region(room, *pos, generation)
    async with server(args, room, port, 'verify'):
        for name in ('Builder', 'Witness'):
            obs = SceneObserver(name)
            link = await asyncio.start_server(lambda r, w: proxy(r, w, port, obs), '127.0.0.1', 0)
            async with link, client(args, room, link.sockets[0].getsockname()[1], name):
                await until(lambda: obs.error is not None or obs.seen == CHUNKS.keys(), f'{name} saw both snapshots', 35)
                assert obs.error is None, obs.error
    print('PASS: persisted attachment snapshots follow centre and streamed chunk packets in the same batch')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', type=Path, default=DATA / 'components/create-atlas-beta.1/target/plain/release/horizon-client.exe')
    parser.add_argument('--pumpkin', type=Path, default=HERE.parent / '.cache/core-target/debug/pumpkin.exe')
    parser.add_argument('--resources', type=Path, default=DATA / 'resources-create-v4')
    parser.add_argument('--create-jar', type=Path)
    args = parser.parse_args()
    for key, path in vars(args).items():
        if path is not None:
            setattr(args, key, path.resolve(strict=True))
    room = Path(tempfile.mkdtemp(prefix='create-scene-wire-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
