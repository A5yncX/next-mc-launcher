"""Two Horizon clients verify moving plough tilling, mob push and restart recovery."""
import asyncio
import math
import socket

from smoke_bearing_motion import ANCHOR, BEARING, MOTOR, STATE, click, observe, run, watch
from smoke_core import CONFIG, server
from smoke_encasing import move
from smoke_harvester import ARM, CROP, TOOL, HarvesterObserver
from smoke_placement import coords, eventually, state_on
from smoke_windmill import change_motion_setting

ID = 'create:mechanical_plough'
PLOUGH = f'{ID}[facing=north,waterlogged=false]'
SOILS = {
    (CROP[0], CROP[1] - 1, CROP[2]): ('rooted_dirt', 'farmland[moisture=0]'),
    (-264, 79, -110): ('grass_block[snowy=false]', 'farmland[moisture=0]'),
    (-264, 79, -111): ('coarse_dirt', 'farmland[moisture=0]'),
    (-265, 79, -111): ('dirt_path', 'farmland[moisture=0]'),
    (-266, 79, -111): ('stone', 'stone'),
    (-267, 79, -111): ('dirt', 'dirt'),
}
OBSTRUCTION = (-267, 80, -111)


class PloughObserver(HarvesterObserver):
    def geometry(self, tag):
        assert tag['ReturnHome'] == ('b', 0)
        states = {tuple(part['Pos'][1]): part['State'] for part in tag['Blocks']}
        assert states == {
            (0, 0, 0): {'id': 'minecraft:slime_block'},
            (1, 0, 0): {'id': 'minecraft:slime_block'},
            (2, 0, 0): {'id': 'minecraft:slime_block'},
            (3, 0, 0): {'id': ID, 'properties': {'facing': 'north', 'waterlogged': 'false'}},
        }, states


async def check_field(peers):
    for call, _ in peers:
        for pos, (_, expected) in SOILS.items():
            await state_on(call, pos, f'minecraft:{expected}')
        await state_on(call, OBSTRUCTION, 'minecraft:stone')
        await eventually(lambda: call('entities 12 minecraft:item'),
                         lambda row: sum(e['item']['count'] for e in row['entities']
                                         if e['item']['item'] == 'minecraft:hanging_roots') == 1,
                         'exactly one hanging roots drop')


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    async with server(args, room, port, 'plough') as (send, _):
        async with watch(args, room, port, 'Builder', observer=PloughObserver) as builder, \
                   watch(args, room, port, 'Witness', observer=PloughObserver) as witness:
            peers = (builder, witness)
            await asyncio.sleep(2)
            send('gamerule minecraft:random_tick_speed 0', 'time set noon',
                 'fill -270 77 -112 -261 77 -103 stone', 'fill -270 78 -112 -261 84 -103 air',
                 f'setblock {coords(BEARING)} {STATE}', f'setblock {coords(MOTOR)} create:creative_motor[facing=up]',
                 *(f'setblock {coords(pos)} {block}' for pos, block in (ARM | {TOOL: PLOUGH}).items()),
                 *(f'setblock {coords(pos)} minecraft:{block}' for pos, (block, _) in SOILS.items()),
                 f'setblock {coords(OBSTRUCTION)} stone')
            await state_on(witness[0], TOOL, PLOUGH)
            await move(builder[0], send, (-265.5, 78, -104.5))
            log = (args.client_workspace or room) / 'Builder' / 'first-client.log'
            await change_motion_setting(builder[0], log, 0, 2)
            await observe(peers, lambda o: o.tags.get(BEARING, {}).get('ScrollValue') == 2, 'retain cargo on stop')
            x, y, z = CROP
            # NoAI prevents Pumpkin's travel step entirely, including external impulses.
            send(f'summon minecraft:pig {x + .5} {y} {z + .5} '
                 '{attributes:[{id:"minecraft:movement_speed",base:0.0d}]}')
            for call, _ in peers:
                await eventually(lambda: call('entities 12 minecraft:pig'),
                                 lambda r: len(r['entities']) == 1 and abs(r['entities'][0]['pos'][2] - z - .5) < .02,
                                 'pig starts still in the next plough cell')
            await click(builder)
            await observe(peers, lambda o: (o.latest or {}).get('Speed') == 32, 'dry plough moves at the shared RPM')
            for call, _ in peers:
                await eventually(lambda: call('entities 12 minecraft:pig'),
                                 lambda r: len(r['entities']) == 1 and r['entities'][0]['pos'][2] < z + .33,
                                 'pig moves in the direction of the passing plough')
            print('PASS: both clients see the plough push the stationary mob along its motion', flush=True)
            await check_field(peers)
            send(f'setblock {coords(MOTOR)} air')
            await observe(peers, lambda o: (o.latest or {}).get('Speed') == 0, 'stop with exact geometry retained')
    async with server(args, room, port, 'plough-restart') as (send, _):
        async with watch(args, room, port, 'Builder', 'restart-client.log', PloughObserver) as builder, \
                   watch(args, room, port, 'Witness', 'restart-client.log', PloughObserver) as witness:
            peers = (builder, witness)
            await observe(peers, lambda o: (o.latest or {}).get('Speed') == 0 and o.tracker == ('b', 0),
                          'both clients reload the plough and visit tracker')
            await asyncio.sleep(2)
            await move(builder[0], send, (-265.5, 78, -104.5))
            await check_field(peers)
            turn = math.floor(witness[1].latest['Angle'] / 90 + .5) % 4
            dx, dz, face = [(3, 0, 'north'), (0, -3, 'west'), (-3, 0, 'south'), (0, 3, 'east')][turn]
            await click(builder)
            await observe(peers, lambda o: o.latest == {}, 'exact plough landing clears both clients')
            for call, _ in peers:
                await state_on(call, (ANCHOR[0] + dx, ANCHOR[1], ANCHOR[2] + dz),
                               f'{ID}[facing={face},waterlogged=false]')
    print('PASS: moving plough tills, preserves blocked ground and restores its rotated state after restart', flush=True)


if __name__ == '__main__':
    run(test, __doc__)
