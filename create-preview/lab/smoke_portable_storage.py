"""Verify stationary portable interfaces on two actual clients; no docking or transfer."""
import asyncio
import socket

from generate_passive_data import generate
from smoke_bearing_motion import BearingObserver, observe, run, watch
from smoke_core import CONFIG, server
from smoke_depot import inventory_is
from smoke_encasing import move
from smoke_passive_recipes import slots
from smoke_placement import aim, coords, eventually, state_on

ID = 'create:portable_storage_interface'
STATION = (-266, 78, -108)
SUPPORT = (-266, 78, -109)
POWER = (-267, 78, -108)
TABLE = (-264, 78, -108)
STATE = f'{ID}[facing=south]'
INGREDIENTS = ('create:andesite_casing', 'create:chute')


class PortableObserver(BearingObserver):
    states = {STATION: STATE}


async def check(peers, power):
    for call, _ in peers:
        await state_on(call, STATION, STATE)
    await observe(peers, lambda o: all(o.tags.get(STATION, {}).get(k) == v
                                       for k, v in [('Powered', power), ('Timer', 0), ('Distance', 0)]),
                  f'stationary interface redstone={power}, no fabricated dock')


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    generate(room / 'create-lab/datapacks/create-passive')
    async with server(args, room, port, 'portable') as (send, _):
        send('datapack enable "file/create-passive"')
        async with watch(args, room, port, 'Builder', observer=PortableObserver) as builder, \
                   watch(args, room, port, 'Witness', observer=PortableObserver) as witness:
            peers = (builder, witness)
            call = builder[0]
            await asyncio.sleep(2)
            send('fill -270 77 -112 -261 77 -103 stone', 'fill -270 78 -112 -261 82 -103 air',
                 f'setblock {coords(SUPPORT)} minecraft:stone', f'setblock {coords(TABLE)} minecraft:crafting_table',
                 'gamemode survival Builder', *(f'give Builder {name} 1' for name in INGREDIENTS))
            await state_on(call, TABLE, 'minecraft:crafting_table')
            await move(call, send, (-264.5, 78, -105.5))
            await aim(call, (-263.5, 78.6, -107.01), TABLE)
            await call('use-item')
            await eventually(lambda: call('screen'), lambda s: s.get('craft_size') == 3, 'actual crafting table')
            for cell, name in enumerate(INGREDIENTS, start=100):
                inv = await inventory_is(call, name, 1)
                src = next(row['slot'] for row in inv['hotbar'] + inv['main'] if row['item'] == name)
                await call(f'click-slot {src}')
                await call(f'click-slot {cell}')
            await eventually(lambda: call('menu'), lambda m: slots(m).get(200) == (ID, 1), 'pinned interface recipe')
            await asyncio.sleep(.25)
            await call('click-slot 200 shift')
            await call('key esc tap')
            await inventory_is(call, ID, 1)
            for name in INGREDIENTS:
                await inventory_is(call, name, 0)
            await move(call, send, (-265.5, 78, -104.5))
            await aim(call, (-265.5, 78.6, -108.02), SUPPORT)
            await call(f'select {ID}')
            await asyncio.sleep(.3)
            await call('use-item')
            await inventory_is(call, ID, 0)
            await check(peers, 0)
            send(f'setblock {coords(POWER)} minecraft:redstone_block')
            await check(peers, 1)
    async with server(args, room, port, 'portable-restart') as (send, _):
        async with watch(args, room, port, 'Builder', 'restart-client.log', PortableObserver) as builder, \
                   watch(args, room, port, 'Witness', 'restart-client.log', PortableObserver) as witness:
            peers = (builder, witness)
            await check(peers, 1)
            send(f'setblock {coords(POWER)} minecraft:air', 'give Builder minecraft:iron_pickaxe 1')
            await check(peers, 0)
            call = builder[0]
            await inventory_is(call, 'minecraft:iron_pickaxe', 1)
            await asyncio.sleep(2)
            await move(call, send, (-265.5, 78, -105.5))
            await call('select minecraft:iron_pickaxe')
            await asyncio.sleep(.3)
            result = await call(f'break {coords(STATION)} --timeout 18')
            assert result.get('block') == 'minecraft:air' and result.get('drops') == {ID: 1}, result
            await state_on(witness[0], STATION, 'minecraft:air')
    print('PASS: real recipe, placement, redstone and restart, and one survival drop', flush=True)


if __name__ == '__main__':
    run(test, __doc__)
