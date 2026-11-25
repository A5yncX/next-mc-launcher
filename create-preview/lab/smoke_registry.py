"""Verify the complete pinned Create registry on two Horizon clients and after server restart."""
import argparse
import asyncio
from pathlib import Path
import socket
import tempfile

from generate_pumpkin_data import CLIENT, read_json
from generate_full_registry import create_ids
from smoke_core import CONFIG, DATA, HERE, ROOT, server, until
from smoke_placement import aim, client, coords, eventually

LOW, HIGH = (-272, 78, -112), (-254, 78, -106)
SAMPLES = ('andesite_casing', 'large_cogwheel', 'water_wheel', 'depot', 'mechanical_press', 'mechanical_pump')


def state_name(row):
    return row['id'] + ('[' + ','.join(f'{k}={v}' for k, v in sorted(row['properties'].items())) + ']'
                        if row.get('properties') else '')


def inventory_has(reply, item):
    return any(slot.get('item') == item for key in ('hotbar', 'main') for slot in reply[key] if slot)


async def expect_states(call, placements, label):
    command = f'blocks {coords(LOW)} {coords(HIGH)}'
    actual = {}

    def matches(reply):
        actual.clear()
        actual.update({(x, y, z): name for x, y, z, name in reply['blocks']})
        return all(actual.get(pos) == name for pos, name in placements.items())

    try:
        await eventually(lambda: call(command), matches, label, 35)
    except AssertionError as exc:
        raise AssertionError((label, [(pos, want, actual.get(pos)) for pos, want in placements.items()
                                      if actual.get(pos) != want][:12])) from exc
    print(f'PASS: {label} ({len(placements)} states)', flush=True)


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    facts = read_json(args.client_cache / 'facts.json')
    ids = create_ids(read_json(args.client_cache / 'registries.json'), 'block')
    last_states = {row[0]: row[4] for row in facts['states'] if row[0] in ids}
    gallery = {(LOW[0] + i % 16, LOW[1], LOW[2] + i // 16): state_name(last_states[name])
               for i, name in enumerate(sorted(ids, key=ids.get))}
    # A playable gallery must leave room for multiblock parts and use stable unpowered states.
    wheel = next(pos for pos, state in gallery.items() if state.startswith('create:large_water_wheel['))
    gallery.pop(wheel)
    gallery[(-254, 78, -109)] = 'create:large_water_wheel[axis=x,extension=false]'
    stable = {
        'create:blaze_burner': 'create:blaze_burner[blaze=smouldering,facing=east]',
        'create:fluid_pipe': 'create:fluid_pipe[down=false,east=true,north=false,south=false,up=false,waterlogged=true,west=true]',
        'create:gantry_shaft': 'create:gantry_shaft[facing=up,part=single,powered=false]',
        'create:sticker': 'create:sticker[extended=false,facing=up,powered=false]',
    }
    unpowered = {'create:adjustable_chain_gearshift', 'create:andesite_funnel',
                 'create:brass_funnel', 'create:clutch', 'create:gearshift'}
    for pos, state in list(gallery.items()):
        name = state.split('[')[0]
        if name in unpowered:
            gallery[pos] = state.replace('powered=true', 'powered=false')
        elif name in stable:
            gallery[pos] = stable[name]
        elif name in {'create:crushing_wheel', 'create:crushing_wheel_controller'}:
            del gallery[pos]
    crusher = 'create:crushing_wheel[axis=z]'
    gallery[(-256, 78, -106)] = crusher
    gallery[(-255, 78, -106)] = 'create:crushing_wheel_controller[facing=down,valid=false]'
    assert len(gallery) == 106 and len({name.split('[')[0] for name in gallery.values()}) == 106
    placed = {}
    async with server(args, room, port, 'registry') as (send, contains):
        async with client(args, room, port, 'RegistryBuilder') as (build, _), \
                client(args, room, port, 'RegistryWitness') as (see, _):
            for call in (build, see):
                await eventually(lambda: call(f'block {coords(LOW)}'), lambda row: row['loaded'], 'gallery chunk loaded')
            send('time set noon', 'fill -272 77 -112 -257 77 -99 stone',
                 'fill -272 78 -112 -257 81 -99 air',
                 'fill -255 77 -111 -253 79 -107 air',
                 'fill -256 78 -106 -254 78 -106 air',
                 f'setblock -254 78 -106 {crusher}',
                 *(f'setblock {coords(pos)} {name}' for pos, name in gallery.items()))
            await asyncio.gather(expect_states(build, gallery, 'Builder received the complete gallery'),
                                 expect_states(see, gallery, 'Witness received the complete gallery'))
            chute = next(pos for pos, name in gallery.items() if name.startswith('create:chute['))
            send(f'setblock {coords(chute)} create:chute[shape=plain]')
            await until(lambda: contains('create:chute[shape=plain]'), 'chute rejects a tank-only shape', 15)
            assert (await see(f'block {coords(chute)}'))['state'] == gallery[chute]
            for i, name in enumerate(SAMPLES):
                item = f'create:{name}'
                x = -269 + 2 * i
                pos = (x, 78, -103)
                send(f'give RegistryBuilder {item} 1', f'tp RegistryBuilder {x + .5} 78 -100.5')
                await eventually(lambda: build('state'), lambda r: abs(r['player']['position'][0] - x - .5) < .1,
                                 'Builder in placement range')
                await eventually(lambda: build('inventory'), lambda r: inventory_has(r, item), f'has {item}')
                await build(f'select {item}')
                await aim(build, (x + .5, 77.99, -102.5), (x, 77, -103))
                await build('use-item')
                command = f'block {coords(pos)}'
                state = await eventually(lambda: see(command), lambda row: row['block'] == item,
                                         f'right-click placed {item}')
                placed[pos] = state['state']
                await eventually(lambda: build(command), lambda row: row['state'] == placed[pos],
                                 f'Builder applied authoritative {item} state')
                print(f'PASS: both clients see right-click placement of {item}', flush=True)
            await build(f'screenshot {(room / "create-gallery.png").as_posix()}')
    reconnect = room / 'reconnect'
    reconnect.mkdir()
    async with server(args, room, port, 'restart') as (_, __):
        async with client(args, reconnect, port, 'RegistryBuilder') as (again, _):
            await expect_states(again, gallery, 'Restart restored every gallery state')
            for pos, expected in placed.items():
                await eventually(lambda: again(f'block {coords(pos)}'), lambda row: row['state'] == expected,
                                 f'restart restored {expected}')
            await eventually(lambda: again('inventory'), lambda row: all(inventory_has(row, f'create:{name}') for name in SAMPLES),
                             'restart restored all six Create inventory stacks')
            print('PASS: six right-click placements and all six Create inventory stacks persisted', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', type=Path, default=ROOT / 'research_create_rust/.create-lab-build/game-target/fast/horizon-client.exe')
    parser.add_argument('--pumpkin', type=Path, default=HERE.parent / '.cache/core-target/debug/pumpkin.exe')
    parser.add_argument('--resources', type=Path, default=DATA / 'resources-create-v4')
    parser.add_argument('--client-cache', type=Path, default=CLIENT)
    parser.add_argument('--create-jar', type=Path, help='optional, locally obtained Create 6.0.10 asset source')
    args = parser.parse_args()
    for attr in ('client', 'pumpkin', 'resources', 'client_cache', 'create_jar'):
        if path := getattr(args, attr):
            setattr(args, attr, path.resolve(strict=True))
    room = Path(tempfile.mkdtemp(prefix='create-registry-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
