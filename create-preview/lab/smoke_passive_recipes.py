"""Run the pinned vanilla crafting and stonecutting transactions through real Horizon menus."""
import argparse
import asyncio
from collections import Counter
import json
from pathlib import Path
import socket
import tempfile

from generate_passive_data import GAUGE_RECIPES, generate
from smoke_core import CONFIG, DATA, HERE, ROOT, server
from smoke_depot import inventory_is
from smoke_encasing import move
from smoke_placement import aim, client, coords, eventually, state_on

TABLE, CUTTER = (-268, 78, -110), (-264, 78, -110)
INGREDIENTS = {
    '#c:ingots/brass': 'create:brass_ingot', '#c:ingots/zinc': 'create:zinc_ingot',
    '#c:ingots/iron': 'minecraft:iron_ingot', '#create:stone_types/andesite': 'minecraft:andesite',
    '#create:stone_types/diorite': 'minecraft:diorite', '#create:stone_types/granite': 'minecraft:granite',
}


def slots(menu):
    return {s['slot']: (s['stack']['item'], s['stack']['count']) for s in menu['slots']}


def ingredient(recipe):
    if recipe['type'] == 'minecraft:crafting_shaped':
        pattern = ''.join(recipe['pattern'])
        assert len(pattern) == 9 and len(set(pattern)) == 1 and pattern[0] != ' ', recipe
        given, amount = recipe['key'][pattern[0]], 9
    else:
        given, amount = recipe['ingredient'], 1
    return INGREDIENTS.get(given, given), amount


async def transact(build, send, key, recipe, expected):
    shaped = recipe['type'] == 'minecraft:crafting_shaped'
    item, amount = ingredient(recipe)
    output = recipe['result']['id'], recipe['result']['count']
    pos = TABLE if shaped else CUTTER
    inventory = await inventory_is(build, item, expected[item])
    slot = next(s['slot'] for s in inventory['hotbar'] + inventory['main'] if s['item'] == item)
    await move(build, send, (pos[0] + .5, pos[1], pos[2] + 2.5))
    await aim(build, tuple(v + .5 for v in pos), pos)
    await build('use-item')
    await eventually(lambda: build('screen'), lambda s: s.get('craft_size') == 3 if shaped else
                     s.get('kind') == 'station' or s.get('station') == 'Stonecutter', 'open real station')
    await build(f'click-slot {slot}')
    if shaped:
        for i in range(100, 109):
            await build(f'click-slot {i} right')
        expected_slot = 200
    else:
        await build('click-slot 600 right')
        if (await build('inventory'))['carried']:
            await build(f'click-slot {slot}')
        menu = await eventually(lambda: build('menu'), lambda m: key in m.get('info', {}).get('recipes', []), key)
        all_recipes = menu['info']['recipes']
        index = all_recipes.index(key)
        start = max(0, (index // 4 - 2) * 4)
        if start:
            scroll_rows = (len(all_recipes) + 3) // 4 - 3
            await build(f'click-gui 123 {15 + 39 * (start // 4) / scroll_rows}')
        on_page = index - start
        await build(f'click-gui {60 + on_page % 4 * 16} {23 + on_page // 4 * 18}')
        expected_slot = 650
    await eventually(lambda: build('menu'), lambda m: slots(m).get(expected_slot) == output,
                     f'{key} result {output}')
    await asyncio.sleep(.25)
    assert slots(await build('menu')).get(expected_slot) == output, (key, await build('menu'))
    await build(f'click-slot {expected_slot} shift')
    await build('key esc tap')
    expected[item] -= amount
    expected[output[0]] += output[1]
    await inventory_is(build, item, expected.get(item, 0))
    await inventory_is(build, output[0], expected[output[0]])
    print(f'PASS: {key} consumes {amount} {item} and produces {output}', flush=True)


async def test(args, room):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port))
    pack = room / 'create-lab/datapacks/create-passive'
    generate(pack)
    recipe_root = pack / 'data/create/recipe'
    recipes = [(f'create:{p.relative_to(recipe_root).with_suffix("").as_posix()}', recipe)
               for p in sorted(recipe_root.rglob('*.json'))
               if p.relative_to(recipe_root).as_posix() not in GAUGE_RECIPES
               and (recipe := json.loads(p.read_text()))['type'] in ('minecraft:crafting_shaped', 'minecraft:stonecutting')]
    assert len(recipes) == 22
    expected = Counter()
    for _, recipe in recipes:
        item, amount = ingredient(recipe)
        expected[item] += amount
    assert len(expected) <= 9 and max(expected.values()) <= 64
    async with server(args, room, port, 'recipes') as (send, _):
        send('datapack enable "file/create-passive"')
        async with client(args, room, port, 'Builder') as (build, _):
            await asyncio.sleep(2)
            send('fill -271 77 -112 -260 77 -105 stone', 'fill -271 78 -112 -260 82 -105 air',
                 f'setblock {coords(TABLE)} crafting_table', f'setblock {coords(CUTTER)} stonecutter',
                 'gamemode survival Builder')
            await state_on(build, TABLE, 'minecraft:crafting_table')
            # Seed the fixture once, outside stations, so no later menu close can overwrite it.
            send(*(f'item replace entity Builder hotbar.{slot} with {item} {amount}'
                   for slot, (item, amount) in enumerate(expected.items())))
            for item, amount in expected.items():
                await inventory_is(build, item, amount)
            for key, recipe in recipes:
                await transact(build, send, key, recipe, expected)
    reconnect = room / 'reconnect'
    reconnect.mkdir()
    async with server(args, room, port, 'restart'):
        async with client(args, reconnect, port, 'Builder') as (build, _):
            for item, count in expected.items():
                await inventory_is(build, item, count)
    print('PASS: all 22 recipe transactions persisted the expected inventory after restart', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', type=Path, default=ROOT / 'research_create_rust/.create-lab-build/game-target/fast/horizon-client.exe')
    parser.add_argument('--pumpkin', type=Path, default=HERE.parent / '.cache/core-target/debug/pumpkin.exe')
    parser.add_argument('--resources', type=Path, default=DATA / 'resources-create-v4')
    parser.add_argument('--create-jar', type=Path)
    args = parser.parse_args()
    for attr, path in vars(args).items():
        if path is not None:
            setattr(args, attr, path.resolve(strict=True))
    room = Path(tempfile.mkdtemp(prefix='create-recipes-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
