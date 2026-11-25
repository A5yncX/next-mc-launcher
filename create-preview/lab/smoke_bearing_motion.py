"""Two real Horizon clients exercise saved, rotating mechanical-bearing cargo."""
import argparse
import asyncio
from contextlib import asynccontextmanager
import io
import math
from pathlib import Path
import socket
import struct
import tempfile

from generate_full_registry import create_ids
from generate_pumpkin_data import CLIENT, read_json
from smoke_core import CONFIG, DATA, HERE, ROOT, Observation, block_pos, proxy, server, until, varint
from smoke_encasing import move
from smoke_placement import aim, client, coords, state_on
from smoke_scene_snapshot import CHANNEL, KEYS, read_tag

BEARING = (-266, 79, -108)
ANCHOR = (-266, 80, -108)
ARM = (-265, 80, -108)
MOTOR = (-266, 78, -108)
CHUNK = (-17, -7)
STATE = 'create:mechanical_bearing[facing=up]'


class BearingObserver(Observation):
    states = {BEARING: STATE}

    def __init__(self, name):
        ids = create_ids(read_json(CLIENT / 'registries.json'), 'block_entity_type')
        super().__init__(name, {pos: (state, ids[state.split('[')[0]]) for pos, state in self.states.items()})
        self.latest = None
        self.angles = set()
        self.clicks = []
        self.ack = -1

    def client_packet(self, number, raw):
        if number == 66:  # UseItemOn
            hand, offset = varint(raw)
            _, face_end = varint(raw, offset + 8)
            sequence, _ = varint(raw, face_end + 14)  # cursor and two flags
            self.clicks.append((hand, block_pos(raw[offset:]), sequence))

    def packet(self, number, raw):
        super().packet(number, raw)
        if number == 4:  # BlockChangedAck
            self.ack = max(self.ack, varint(raw)[0])
        channel = bytes([len(CHANNEL)]) + CHANNEL
        if number != 24 or not raw.startswith(channel):
            return
        stream = io.BytesIO(raw[len(channel):])
        kind, x, z, replace, count = struct.unpack('>BiiBB', stream.read(11))
        if (x, z) != CHUNK:
            return
        assert (kind, replace, count) == (3, 1, 2)
        tags = []
        for key, version in zip(KEYS, (2, 1), strict=True):
            assert stream.read(7) == b'\x06create'
            assert stream.read(stream.read(1)[0]).decode() == key
            assert stream.read(1) == b'\x0a'
            data = read_tag(stream, 10)
            assert data['Version'] == version
            tags.append(data)
        assert not stream.read() and tags[0]['Generation'] == tags[1]['Generation']
        self.records(*(s['Entries'] for s in tags))

    def records(self, geo, pose):
        if not geo:
            assert not pose
            self.latest = {}
            return
        assert len(geo) == len(pose) == 1
        assert geo[0]['Controller'] == pose[0]['Controller'] == ('I', list(BEARING))
        assert geo[0]['Anchor'] == ('I', list(ANCHOR)) and geo[0]['Axis'] == 1
        self.geometry(geo[0])
        self.latest = {k: pose[0][k][1] for k in ('Angle', 'PreviousAngle', 'Speed', 'Stalled')}
        if self.latest['Speed']:
            self.angles.add(self.latest['Angle'])

    def geometry(self, tag):
        assert tag['ReturnHome'] == ('b', 0)
        assert {tuple(b['Pos'][1]): b['State']['id'] for b in tag['Blocks']} == {
            (0, 0, 0): 'minecraft:slime_block', (1, 0, 0): 'minecraft:andesite'}


@asynccontextmanager
async def watch(args, room, port, name, log_name='first-client.log', observer=BearingObserver):
    obs = observer(name)
    link = await asyncio.start_server(lambda r, w: proxy(r, w, port, obs, obs.client_packet), '127.0.0.1', 0)
    client_room = args.client_workspace or room
    async with link, client(args, client_room, link.sockets[0].getsockname()[1], name, log_name) as (call, _):
        yield call, obs
    assert obs.error is None, obs.error


async def click(builder):
    call, obs = builder
    prior = len(obs.clicks)
    # Aim high on the bearing rim, above its motion-settings board.
    hit = await aim(call, (-265.5, 79.78, -107.08), BEARING)
    await asyncio.sleep(.3)
    await call('use-item')
    try:
        await until(lambda: any(h == 0 and p == BEARING for h, p, _ in obs.clicks[prior:]),
                    'client forwards the main-hand bearing click', 4)
    except TimeoutError as e:
        raise AssertionError(f'no bearing packet for hit {hit!r}: {obs.clicks!r}; {obs.error!r}') from e
    seq = next(s for h, p, s in obs.clicks[prior:] if h == 0 and p == BEARING)
    await until(lambda: obs.error is not None or obs.ack >= seq, 'server acknowledges the bearing click', 8)
    assert obs.error is None, obs.error


async def observe(peers, check, label):
    try:
        await until(lambda: any(o.error is not None for _, o in peers) or all(check(o) for _, o in peers), label, 30)
    except TimeoutError:
        print([(o.latest, o.angles, o.tags.get(BEARING), o.error, o.clicks) for _, o in peers], flush=True)
        raise
    assert all(o.error is None for _, o in peers), [o.error for _, o in peers]


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))

    async with server(args, room, port, 'bearing-motion') as (send, _):
        async with watch(args, room, port, 'Builder') as builder, watch(args, room, port, 'Witness') as witness:
            peers = (builder, witness)
            await asyncio.sleep(2)
            send('fill -269 77 -112 -261 77 -103 stone', 'fill -269 78 -112 -261 84 -103 air',
                 f'setblock {coords(MOTOR)} create:creative_motor[facing=up]', f'setblock {coords(BEARING)} {STATE}',
                 f'setblock {coords(ANCHOR)} minecraft:chest', 'gamemode survival Builder')
            await state_on(builder[0], BEARING, STATE)
            await move(builder[0], send, (-265.5, 78, -104.5))
            await observe(peers, lambda o: o.tags.get(BEARING, {}).get('Speed') == 32, 'vertical motor drives bearing')
            await click(builder)
            assert all(o.latest is None for _, o in peers), 'unsafe block was captured'
            await state_on(witness[0], ANCHOR, 'minecraft:chest[facing=north,type=single,waterlogged=false]')
            send(f'setblock {coords(ANCHOR)} slime_block', f'setblock {coords(ARM)} andesite')
            await state_on(builder[0], ARM, 'minecraft:andesite')
            await click(builder)
            await observe(peers, lambda o: len(o.angles) >= 4 and o.tags.get(BEARING, {}).get('Running') == 1,
                          'both clients see identical cargo, Running and advancing poses')
            for call, _ in peers:
                await state_on(call, ANCHOR, 'minecraft:air')
                await state_on(call, ARM, 'minecraft:air')
            send(f'setblock {coords(ANCHOR)} granite')
            await state_on(builder[0], ANCHOR, 'minecraft:granite')
            await click(builder)
            await observe(peers, lambda o: (o.latest or {}).get('Stalled') == 1, 'blocked landing holds cargo and pose')
            held = witness[1].latest['Angle']
            send(f'setblock {coords(BEARING)} air')
            await asyncio.sleep(.3)
            await state_on(witness[0], BEARING, STATE)
            await state_on(witness[0], ANCHOR, 'minecraft:granite')
            await builder[0](f'screenshot {room / "blocked-landing.png"}')
    async with server(args, room, port, 'restart') as (send, _):
        async with watch(args, room, port, 'Builder', 'restart-client.log') as builder, \
                   watch(args, room, port, 'Witness', 'restart-client.log') as witness:
            peers = (builder, witness)
            await observe(peers, lambda o: (o.latest or {}).get('Stalled') == 1 and o.latest['Angle'] == held,
                          'saved blocked pose and exact cargo received after restart')
            await asyncio.sleep(2)
            await move(builder[0], send, (-265.5, 78, -104.5))
            send(f'setblock {coords(ANCHOR)} air')
            await state_on(builder[0], ANCHOR, 'minecraft:air')
            await click(builder)
            await observe(peers, lambda o: o.latest == {} and o.tags.get(BEARING, {}).get('Running', 0) == 0,
                          'successful safe landing clears both clients')
            steps = math.floor(held / 90 + 0.5) % 4
            offsets = ((1, 0), (0, -1), (-1, 0), (0, 1))
            for call, _ in peers:
                await state_on(call, ANCHOR, 'minecraft:slime_block')
                for i, (dx, dz) in enumerate(offsets):
                    await state_on(call, (ANCHOR[0] + dx, ANCHOR[1], ANCHOR[2] + dz),
                                   'minecraft:andesite' if i == steps else 'minecraft:air')
    print('PASS: unsupported block rejected; two-block rotation, stalled restart and exact snapped landing', flush=True)


def run(test_case, description):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument('--client', type=Path, default=ROOT / 'research_create_rust/.create-lab-build/game-target/fast/horizon-client.exe')
    parser.add_argument('--pumpkin', type=Path, default=HERE.parent / '.cache/core-target/debug/pumpkin.exe')
    parser.add_argument('--resources', type=Path, default=DATA / 'resources-create-v4')
    parser.add_argument('--create-jar', type=Path)
    parser.add_argument('--startup-timeout', type=int, default=480)
    parser.add_argument('--client-workspace', type=Path, help='reuse Builder/Witness cache from an isolated smoke run')
    args = parser.parse_args()
    for key, path in vars(args).items():
        if isinstance(path, Path):
            setattr(args, key, path.resolve(strict=True))
    room = Path(tempfile.mkdtemp(prefix='bearing-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test_case(args, room))


if __name__ == '__main__':
    run(test, __doc__)
