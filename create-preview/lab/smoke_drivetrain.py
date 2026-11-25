"""Check Create gear ratios and per-face gearbox speed on two real Horizon clients."""
from contextlib import asynccontextmanager
import argparse
import asyncio
from pathlib import Path
import socket
import tempfile

from generate_full_registry import create_ids
from generate_pumpkin_data import CLIENT, read_json
from smoke_core import CONFIG, DATA, HERE, ROOT, Observation, proxy, server, until
from smoke_placement import aim, client, coords, eventually, state_on

LARGE = (-268, 78, -108)
SMALL = (-268, 79, -107)
FLYWHEEL = (-267, 79, -107)
GEARBOX = (-262, 78, -107)
STATES = {
    (-269, 78, -108): ('creative_motor[facing=east]', 32),
    LARGE: ('large_cogwheel[axis=x,waterlogged=false]', 32),
    SMALL: ('andesite_encased_cogwheel[axis=x,bottom_shaft=false,top_shaft=true]', -64),
    FLYWHEEL: ('flywheel[axis=x]', -64),
    (-265, 78, -107): ('creative_motor[facing=east]', 32),
    (-264, 78, -107): ('andesite_encased_shaft[axis=x]', 32),
    (-263, 78, -107): ('brass_encased_shaft[axis=x]', 32),
    GEARBOX: ('gearbox[axis=y]', -32),
    (-262, 78, -106): ('shaft[axis=z,waterlogged=false]', 32),
}


@asynccontextmanager
async def watch(args, room, port, name, targets):
    observer = Observation(name, targets)
    link = await asyncio.start_server(lambda r, w: proxy(r, w, port, observer), '127.0.0.1', 0)
    async with link, client(args, room, link.sockets[0].getsockname()[1], name) as (call, _):
        yield call, observer
        assert observer.error is None, observer.error


def correct_gearbox_ports(observer):
    try:
        ports = observer.tags[GEARBOX]['create_horizon']['Ports']
    except KeyError:
        return False
    return ports == dict(west=32, east=-32, north=-32, south=32, up=0, down=0)


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    ids = create_ids(read_json(CLIENT / 'registries.json'), 'block_entity_type')
    targets = {pos: ('create:' + block, ids['create:' + block.split('[')[0]])
               for pos, (block, _) in STATES.items()}
    async with server(args, room, port, 'drivetrain') as (send, _):
        async with watch(args, room, port, 'Builder', targets) as (build, one), \
                watch(args, room, port, 'Witness', targets) as (see, two):
            await asyncio.sleep(2)
            send('fill -272 77 -111 -257 77 -100 stone', 'fill -272 78 -111 -257 82 -100 air',
                 'setblock -267 78 -107 stone', 'tp Builder -266.5 78 -104.5',
                 'give Builder create:flywheel 1',
                 *(f'setblock {coords(pos)} {targets[pos][0]}' for pos in targets if pos != FLYWHEEL))
            await state_on(build, SMALL, targets[SMALL][0])
            await eventually(lambda: build('state'), lambda r: abs(r['player']['position'][0] + 266.5) < .1,
                             'Builder reached the flywheel placement')
            await build('select create:flywheel')
            await aim(build, (-266.5, 78.99, -106.5), (-267, 78, -107))
            await build('use-item')
            for call in (build, see):
                await state_on(call, FLYWHEEL, targets[FLYWHEEL][0])
            await until(lambda: all(all((pos, targets[pos][1], rpm) in o.updates for pos, (_, rpm) in STATES.items())
                                    and correct_gearbox_ports(o) for o in (one, two)),
                        'both clients: large/small ratio -2, rotating flywheel and signed gearbox ports', 22)
            for o in one, two:
                o.updates.clear()
            send(f'setblock {coords(SMALL)} create:andesite_encased_cogwheel[axis=x,bottom_shaft=false,top_shaft=false]')
            await until(lambda: all((FLYWHEEL, targets[FLYWHEEL][1], 0) in o.updates for o in (one, two)),
                        'closing the encased cog port stops the flywheel', 15)
            for o in one, two:
                o.updates.clear()
            send(f'setblock {coords(SMALL)} {targets[SMALL][0]}')
            await until(lambda: all((FLYWHEEL, targets[FLYWHEEL][1], -64) in o.updates for o in (one, two)),
                        'reopening the port restarts the flywheel', 15)
    reconnect = room / 'reconnect'
    reconnect.mkdir()
    async with server(args, room, port, 'restart') as (_, __):
        async with watch(args, reconnect, port, 'Builder', targets) as (again, observation):
            await until(lambda: observation.initial == {pos: (targets[pos][1], rpm) for pos, (_, rpm) in STATES.items()}
                        and correct_gearbox_ports(observation), 'restart recovered all kinetic entities and gearbox ports', 20)
            for pos, (state, _) in STATES.items():
                await state_on(again, pos, 'create:' + state)


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
    room = Path(tempfile.mkdtemp(prefix='create-drivetrain-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
