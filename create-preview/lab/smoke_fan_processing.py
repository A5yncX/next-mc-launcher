"""Two real Horizon clients verify four fan media, conversions and restart."""
import argparse
import asyncio
from pathlib import Path
import socket
import tempfile

from generate_full_registry import create_ids
from generate_pumpkin_data import CLIENT, read_json
from smoke_core import CONFIG, DATA, HERE, ROOT, server, until
from smoke_drivetrain import watch
from smoke_placement import state_on

FAN = 'create:encased_fan'
FAN_STATE = f'{FAN}[facing=east]'
LANES = (
    (-111, 'create:blaze_burner[blaze=kindled,facing=north]', 1, 'raw_iron', 'iron_ingot'),
    (-109, 'minecraft:soul_campfire[facing=north,lit=true,signal_fire=false,waterlogged=false]', 2, 'stone', 'infested_stone'),
    (-107, 'create:blaze_burner[blaze=smouldering,facing=north]', 3, 'beef', 'cooked_beef'),
    (-105, 'minecraft:iron_bars[east=false,north=false,south=false,waterlogged=true,west=false]', 4, 'ice', 'packed_ice'),
)


def channel(observer, position):
    data = observer.tags.get(position, {}).get('CreateHorizonAirCurrent', [])
    if len(data) >= 8:
        return tuple(data[6:5 + 2 * data[4]:2])
    return ()


async def counts(call):
    result = {}
    for row in (await call('entities 18 minecraft:item'))['entities']:
        item = row['item']
        result[item['item']] = result.get(item['item'], 0) + item['count']
    return result


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    entity_id = create_ids(read_json(CLIENT / 'registries.json'), 'block_entity_type')[FAN]
    targets = {(-269, 78, z): (FAN, entity_id) for z, *_ in LANES}
    raw = {f'minecraft:{item}': 2 for _, _, _, item, _ in LANES}
    cooked = {f'minecraft:{result}': 2 for _, _, _, _, result in LANES}

    async with server(args, room, port, 'fan-processing') as (send, _):
        async with watch(args, room, port, 'Builder', targets) as (build, a), \
                watch(args, room, port, 'Witness', targets) as (see, b):
            await asyncio.sleep(2)
            send('fill -274 77 -114 -260 77 -102 stone', 'fill -274 78 -114 -260 82 -102 air',
                 'fill -266 78 -112 -266 81 -104 stone',
                 'fill -268 78 -106 -267 80 -106 stone', 'fill -268 78 -104 -267 80 -104 stone',
                 'kill @e[type=minecraft:item]')
            for z, catalyst, _, _, _ in LANES:
                send(f'setblock -268 78 {z} {catalyst}')
                await state_on(see, (-268, 78, z), catalyst)
                send(f'setblock -269 78 {z} {FAN_STATE}', f'setblock -270 78 {z} create:creative_motor[facing=east]')
            # Check both version-2 wire decoders before introducing items.
            await until(lambda: all(code in channel(o, (-269, 78, z))
                                    for z, _, code, _, _ in LANES for o in (a, b)),
                        'four media segments reached both clients')
            for z, _, _, item, _ in LANES:
                send(f'summon minecraft:item -267.25 78.1 {z + .5} {{Item:{{id:"minecraft:{item}",count:2}},PickupDelay:32767s}}')
            await asyncio.sleep(2)
            for client in (build, see):
                observed = await counts(client)
                assert observed == raw, observed
            print('PASS: first stop before processing finishes; both clients see exact inputs', flush=True)

    reconnect = room / 'reconnect'
    reconnect.mkdir()
    async with server(args, room, port, 'restart') as (_, __):
        async with watch(args, reconnect, port, 'Builder', targets) as (build, a), \
                watch(args, reconnect, port, 'Witness', targets) as (see, b):
            for client in (build, see):
                for _ in range(70):
                    observed = await counts(client)
                    if observed == cooked:
                        break
                    await asyncio.sleep(.3)
                assert observed == cooked, await client('entities 18 minecraft:item')
            print('PASS: restarted fans convert all exact stack counts without leftovers', flush=True)


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
    room = Path(tempfile.mkdtemp(prefix='create-fan-processing-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
