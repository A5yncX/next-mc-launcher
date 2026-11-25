"""Two Horizon clients verify crops, cut plants and exact moving-tool recovery across restart."""
import asyncio
import math
import socket

from smoke_bearing_motion import ANCHOR, BEARING, MOTOR, STATE, BearingObserver, click, observe, run, watch
from smoke_core import CONFIG, server
from smoke_encasing import move
from smoke_placement import coords, eventually, state_on
from smoke_windmill import change_motion_setting

TOOL = (-263, 80, -108)
CROP = (-263, 80, -109)
IMMATURE = (-263, 80, -110)
COCOA_SUPPORT = (-262, 80, -109)
ARM = {ANCHOR: 'minecraft:slime_block', (-265, 80, -108): 'minecraft:slime_block',
       (-264, 80, -108): 'minecraft:slime_block', TOOL: 'create:mechanical_harvester[facing=north,waterlogged=false]'}


class HarvesterObserver(BearingObserver):
    tracker = None

    def records(self, geom, pose):
        super().records(geom, pose)
        self.tracker = None
        if pose and (tracks := pose[0].get('NextMcHarvesters')):
            assert len(tracks) == 1 and tracks[0]['Pos'] == ('I', [3, 0, 0])
            self.tracker = tracks[0]['First']

    def geometry(self, tag):
        assert tag['ReturnHome'] == ('b', 0)
        assert {tuple(p['Pos'][1]): p['State'] for p in tag['Blocks']} == {
            (0, 0, 0): {'id': 'minecraft:slime_block'},
            (1, 0, 0): {'id': 'minecraft:slime_block'},
            (2, 0, 0): {'id': 'minecraft:slime_block'},
            (3, 0, 0): {'id': 'create:mechanical_harvester', 'properties': {'facing': 'north', 'waterlogged': 'false'}},
        }, tag['Blocks']


def drops(row):
    counts = {}
    for entity in row['entities']:
        item = entity['item']
        counts[item['item']] = counts.get(item['item'], 0) + item['count']
    return counts


async def verify_crop(peers, state, expected, saved=None):
    for call, _ in peers:
        await state_on(call, CROP, f'minecraft:{state}')
    # The terrain update precedes its loot; give both clients time to receive all drops.
    await asyncio.sleep(.4)
    for call, _ in peers:
        counts = drops(await call('entities 10 minecraft:item'))
        assert not counts.keys() - expected.keys(), (state, counts)
        assert all(low <= counts.get(k, 0) <= high for k, (low, high) in expected.items()), (state, counts)
        if saved is None:
            saved = counts
        assert counts == saved, (state, counts, saved)
    return saved


async def verify_wheat(peers):
    for call, _ in peers:
        await state_on(call, CROP, 'minecraft:wheat[age=0]')
        await state_on(call, IMMATURE, 'minecraft:wheat[age=3]')
        await state_on(call, (CROP[0], CROP[1] - 1, CROP[2]), 'minecraft:farmland[moisture=7]')
        await eventually(lambda: call('entities 10 minecraft:item'),
                         lambda r: drops(r).get('minecraft:wheat') == 1 and drops(r).get('minecraft:wheat_seeds', 0) <= 3,
                         'exactly one wheat and only surplus seeds')


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    async with server(args, room, port, 'harvester') as (send, _):
        async with watch(args, room, port, 'Builder', observer=HarvesterObserver) as builder, \
                   watch(args, room, port, 'Witness', observer=HarvesterObserver) as witness:
            peers = (builder, witness)
            log = (args.client_workspace or room) / 'Builder' / 'first-client.log'
            await asyncio.sleep(2)
            send('gamerule minecraft:random_tick_speed 0', 'time set noon',
                 'fill -270 77 -112 -261 77 -103 stone', 'fill -270 78 -112 -261 84 -103 air',
                 f'setblock {coords(BEARING)} {STATE}', f'setblock {coords(MOTOR)} create:creative_motor[facing=up]',
                 *(f'setblock {coords(pos)} {block}' for pos, block in ARM.items()),
                 *(line for (x, y, z), age in ((CROP, 7), (IMMATURE, 3))
                   for line in (f'setblock {x} {y-2} {z} minecraft:dirt',
                                f'setblock {x} {y-1} {z} minecraft:farmland[moisture=7]',
                                f'setblock {x} {y} {z} minecraft:wheat[age={age}]')))
            await state_on(witness[0], TOOL, ARM[TOOL])
            await state_on(witness[0], CROP, 'minecraft:wheat[age=7]')
            await move(builder[0], send, (-265.5, 78, -104.5))
            await change_motion_setting(builder[0], log, 0, 2)
            await observe(peers, lambda o: o.tags.get(BEARING, {}).get('ScrollValue') == 2, 'retain cargo on stop')
            await click(builder)
            await observe(peers, lambda o: (o.latest or {}).get('Speed') == 32, 'real clients receive the harvester in motion')
            await verify_wheat(peers)
            soil = (CROP[0], CROP[1] - 1, CROP[2])
            send(f'setblock {coords(soil)} minecraft:dirt',
                 'setblock -262 78 -109 minecraft:stone', 'setblock -261 79 -109 minecraft:stone',
                 'setblock -262 79 -108 minecraft:stone', 'setblock -262 79 -110 minecraft:stone',
                 'setblock -262 79 -109 minecraft:water')
            await state_on(witness[0], soil, 'minecraft:dirt')
            for block, item in (
                ('dandelion', 'dandelion'), ('poppy', 'poppy'),
                ('oak_sapling[stage=0]', 'oak_sapling'), ('birch_sapling[stage=0]', 'birch_sapling'),
                ('oak_leaves[distance=7,persistent=true,waterlogged=false]', 'oak_leaves'),
                ('sugar_cane[age=0]', 'sugar_cane'),
            ):
                send('kill @e[type=minecraft:item]')
                for call, _ in peers:
                    await eventually(lambda: call('entities 10 minecraft:item'), lambda r: not drops(r), 'clear preceding cut')
                send(f'setblock {coords(CROP)} minecraft:{block}')
                for call, _ in peers:
                    await eventually(lambda: call('entities 10 minecraft:item'),
                                     lambda r: drops(r) == {f'minecraft:{item}': 1}, f'exactly one {item}')
                    await state_on(call, CROP, 'minecraft:air')
                    await state_on(call, IMMATURE, 'minecraft:wheat[age=3]')
                print(f'PASS: both clients see {block} cut and exactly one {item}', flush=True)
            above = (CROP[0], CROP[1] + 1, CROP[2])
            send(f'setblock {coords(above)} stone')
            for block, exact_drop in (
                ('twisting_vines[age=0]', None), ('weeping_vines[age=0]', None),
                ('cave_vines[age=0,berries=true]', 'glow_berries'),
            ):
                send('kill @e[type=minecraft:item]')
                for call, _ in peers:
                    await eventually(lambda: call('entities 10 minecraft:item'), lambda r: not drops(r), 'clear preceding cut')
                send(f'setblock {coords(MOTOR)} air')
                await observe(peers, lambda o: (o.latest or {}).get('Speed') == 0, 'pause harvester for vine fixture')
                send(f'setblock {coords(CROP)} minecraft:{block}')
                for call, _ in peers:
                    await state_on(call, CROP, f'minecraft:{block}')
                send(f'setblock {coords(MOTOR)} create:creative_motor[facing=up]')
                for call, _ in peers:
                    await state_on(call, CROP, 'minecraft:air')
                    if exact_drop:
                        await eventually(lambda: call('entities 10 minecraft:item'),
                                         lambda r: drops(r) == {f'minecraft:{exact_drop}': 1}, f'exactly one {exact_drop}')
                print(f'PASS: both clients see supported {block} cut', flush=True)
            # Kelp has intrinsic source water, rather than a waterlogged property.
            x, y, z = CROP
            walls = [(x + 1, y, z), (x - 1, y, z), (x, y, z + 1), (x, y, z - 1)]
            send('kill @e[type=minecraft:item]', *(f'setblock {coords(p)} stone' for p in walls))
            for p in walls:
                await state_on(witness[0], p, 'minecraft:stone')
            for call, _ in peers:
                await eventually(lambda: call('entities 10 minecraft:item'), lambda r: not drops(r), 'clear preceding cut')
            send(f'setblock {coords(CROP)} minecraft:kelp[age=0]')
            for call, _ in peers:
                await state_on(call, CROP, 'minecraft:water[level=0]')
                await eventually(lambda: call('entities 10 minecraft:item'),
                                 lambda r: drops(r) == {'minecraft:kelp': 1}, 'one kelp with source water restored')
            print('PASS: both clients see one kelp and its restored water source', flush=True)
            send(f'setblock {coords(CROP)} air', f'setblock {coords(above)} air',
                 *(f'setblock {coords(p)} air' for p in walls),
                 'setblock -262 79 -109 minecraft:air', f'setblock {coords(soil)} minecraft:farmland[moisture=7]')
            await state_on(witness[0], soil, 'minecraft:farmland[moisture=7]')
            crops = (
                ('carrots', 7, 0, '', {'minecraft:carrot': (1, 4)}),
                ('potatoes', 7, 0, '', {'minecraft:potato': (1, 4), 'minecraft:poisonous_potato': (0, 1)}),
                ('beetroots', 3, 0, '', {'minecraft:beetroot': (1, 1), 'minecraft:beetroot_seeds': (0, 3)}),
                ('nether_wart', 3, 0, '', {'minecraft:nether_wart': (1, 3)}),
                ('sweet_berry_bush', 3, 1, '', {'minecraft:sweet_berries': (1, 2)}),
                ('cocoa', 2, 0, ',facing=east', {'minecraft:cocoa_beans': (2, 2)}),
            )
            for crop, age, replanted, extra, expected in crops:
                send('kill @e[type=minecraft:item]', f'setblock {coords(CROP)} air')
                for call, _ in peers:
                    await state_on(call, CROP, 'minecraft:air')
                    await eventually(lambda: call('entities 10 minecraft:item'), lambda r: not drops(r), 'clear preceding drops')
                if crop == 'nether_wart':
                    send(f'setblock {coords(soil)} minecraft:soul_sand')
                    await state_on(witness[0], soil, 'minecraft:soul_sand')
                elif crop == 'sweet_berry_bush':
                    send(f'setblock {coords(soil)} minecraft:dirt')
                    await state_on(witness[0], soil, 'minecraft:dirt')
                elif crop == 'cocoa':
                    send(f'setblock {coords(COCOA_SUPPORT)} minecraft:jungle_log[axis=y]')
                    await state_on(witness[0], COCOA_SUPPORT, 'minecraft:jungle_log[axis=y]')
                send(f'setblock {coords(CROP)} minecraft:{crop}[age={age}{extra}]')
                final_crop = f'{crop}[age={replanted}{extra}]'
                saved = await verify_crop(peers, final_crop, expected)
                print(f'PASS: {crop} replanted; both clients see {saved}', flush=True)
            send(f'setblock {coords(MOTOR)} air')
            await observe(peers, lambda o: (o.latest or {}).get('Speed') == 0, 'stopped assembly keeps its exact tool state')
    async with server(args, room, port, 'harvester-restart') as (send, _):
        async with watch(args, room, port, 'Builder', 'restart-client.log', HarvesterObserver) as builder, \
                   watch(args, room, port, 'Witness', 'restart-client.log', HarvesterObserver) as witness:
            peers = (builder, witness)
            await observe(peers, lambda o: (o.latest or {}).get('Speed') == 0 and o.tracker == ('b', 0),
                          'both clients reload the dry tool and its first-visit tracker')
            await asyncio.sleep(2)
            await move(builder[0], send, (-265.5, 78, -104.5))
            await verify_crop(peers, final_crop, expected, saved)
            turn = math.floor(witness[1].latest['Angle'] / 90 + .5) % 4
            dx, dz, face = [(3, 0, 'north'), (0, -3, 'west'), (-3, 0, 'south'), (0, 3, 'east')][turn]
            await click(builder)
            await observe(peers, lambda o: o.latest == {}, 'disassembly releases the saved moving tool')
            landed = (ANCHOR[0] + dx, ANCHOR[1], ANCHOR[2] + dz)
            for call, _ in peers:
                await state_on(call, landed, f'create:mechanical_harvester[facing={face},waterlogged=false]')
    print('PASS: mature crop replanted; no duplicate drops; saved tool restored with rotated facing', flush=True)


if __name__ == '__main__':
    run(test, __doc__)
