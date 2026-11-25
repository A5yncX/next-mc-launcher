#!/usr/bin/env python3
"""Import every block/state/item from the pinned Horizon Create 0.9.0 export."""
import argparse
from collections import defaultdict
import hashlib
import json
from math import prod
from pathlib import Path

from generate_passive_data import CONTENT_JSON, LOOT_BLOCKS, _extract_resources
from generate_pumpkin_data import (
    BLOCKS, CLIENT, PUMPKIN, exported_data_digest, read_json, write_compact_json,
)

EXPORT_ID = '06d8f0d5bbe6db6d879e44426a8a8236a033594df7d496a2e50fe22fa3005928'
WIRE_ID = '759a0d8edbe01d868a554e8fe0a9025ed8fa93c6c9aa274348f066d755d4d37b'
KINETIC_BLOCKS = {
    'andesite_encased_cogwheel', 'andesite_encased_large_cogwheel', 'andesite_encased_shaft',
    'brass_encased_cogwheel', 'brass_encased_large_cogwheel', 'brass_encased_shaft',
    'belt', 'clutch', 'flywheel', 'gantry_carriage', 'gantry_shaft', 'gearbox', 'gearshift', 'large_cogwheel', 'large_water_wheel', 'water_wheel',
    'mechanical_piston', 'sticky_mechanical_piston', 'rope_pulley', 'mechanical_bearing', 'clockwork_bearing', 'windmill_bearing',
    'adjustable_chain_gearshift', 'encased_chain_drive', 'hand_crank', 'mechanical_press', 'mechanical_pump', 'fluid_valve', 'speedometer', 'stressometer', 'encased_fan', 'millstone', 'mechanical_drill', 'mechanical_saw', 'crushing_wheel', 'mechanical_mixer', 'deployer', 'mechanical_crafter',
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def create_ids(registries, kind):
    entries = registries[f'minecraft:{kind}']['entries']
    return {name: row['protocol_id'] for name, row in entries.items() if name.startswith('create:')}


def property_hash(properties, key, values):
    def possible(row):
        if row['type'] == 'boolean':
            return {'true', 'false'}
        if row['type'] == 'int':
            return set(map(str, range(row['min'], row['max'] + 1)))
        return set(row['values'])

    values = set(values)
    for row in properties:
        if row['serialized_name'] == key and possible(row) == values:
            return row['hash_key']
    if values == {'true', 'false'}:
        kind = {'type': 'boolean'}
    elif all(value.isdecimal() for value in values):
        numbers = list(map(int, values))
        kind = {'type': 'int', 'min': min(numbers), 'max': max(numbers)}
    else:
        kind = {'type': 'enum', 'values': sorted(values)}
    hash_key = int.from_bytes(hashlib.sha256(repr((key, kind)).encode()).digest()[:4], 'big', signed=True)
    row = dict(kind, serialized_name=key, hash_key=hash_key, enum_name=f'create_{key}_{hash_key & 0xffffffff:x}')
    existing = next((p for p in properties if p['hash_key'] == hash_key), None)
    require(existing is None or existing == row, f'Property ID collision for {key}')
    if existing is None:
        properties.append(row)
    return hash_key


def generate(assets, client):
    facts = read_json(client / 'facts.json')
    registries = read_json(client / 'registries.json')
    require(exported_data_digest(facts, registries).hex() == EXPORT_ID, 'Unrecognized Horizon export')
    blocks, items, entities = [create_ids(registries, kind) for kind in ('block', 'item', 'block_entity_type')]
    states = defaultdict(list)
    for state_id, row in enumerate(facts['states']):
        if row[0].startswith('create:'):
            require(row[0] == row[4]['id'], f'Mismatched state {state_id}')
            states[row[0]].append((state_id, row[4].get('properties', {})))
    require((len(blocks), len(items), len(entities), sum(map(len, states.values()))) == (106, 123, 106, 2145)
            and blocks.keys() == states.keys() == entities.keys(), 'Unexpected Create registry coverage')

    table = read_json(assets / 'blocks.json')
    properties = read_json(assets / 'properties.json')
    item_table = read_json(assets / 'items.json')
    item_components = read_json(client / 'items.json')
    models = read_json(client / 'model-states.json')
    gameplay = read_json(client / 'gameplay-facts.json')['states']
    existing = {block['name']: block for block in table['blocks']}
    vanilla = [block for block in table['blocks'] if not block['name'].startswith('create:')]
    require(set(blocks.values()).isdisjoint(block['id'] for block in vanilla), 'Block ID collision')
    require(set(items.values()).isdisjoint(row['id'] for name, row in item_table.items() if name not in items), 'Item ID collision')
    vanilla_states = {state['id'] for block in vanilla for state in block['states']}
    require(all(i not in vanilla_states for rows in states.values() for i, _ in rows), 'State ID collision')
    require(set(existing) - {block['name'] for block in vanilla} <= blocks.keys(), 'Unrecognized existing Create block')
    glass = existing['glass']
    implemented_entities = {spec['name'] for spec in BLOCKS} | {f'create:{name}' for name in KINETIC_BLOCKS} | {'create:depot', 'create:item_drain', 'create:fluid_tank', 'create:chute', 'create:smart_chute', 'create:crushing_wheel_controller', 'create:linear_chassis', 'create:secondary_linear_chassis', 'create:radial_chassis', 'create:blaze_burner', 'create:basin', 'create:andesite_funnel', 'create:brass_funnel', 'create:portable_storage_interface'}
    require(implemented_entities <= entities.keys(), 'Missing implemented block-entity ID')
    shapes = {tuple(box['min'] + box['max']): index for index, box in reversed(list(enumerate(table['shapes'])))}
    sounds = {sound['break_sound']: i for i, sound in enumerate(table['sound_types'])}
    # Pumpkin decodes names before it knows the block; share the overlapping Create enum values.
    shared = {key: property_hash(properties, key, {
        value for name in blocks for value in models[name]['schema'].get(key, {}).get('named', [])
    }) for key in ('part', 'shape')}

    def shape_id(box):
        key = tuple(box)
        if key not in shapes:
            shapes[key] = len(table['shapes'])
            table['shapes'].append(dict(min=box[:3], max=box[3:]))
        return shapes[key]

    for name, block_id in sorted(blocks.items(), key=lambda pair: pair[1]):
        schema = {k: v['named'] for k, v in sorted(models[name]['schema'].items())}
        rows = states[name]
        require(len(rows) == prod(map(len, schema.values())) == len({tuple(sorted(props.items())) for _, props in rows}),
                f'Incomplete property combinations for {name}')
        require(all(props.keys() == schema.keys() and all(v in schema[k] for k, v in props.items()) for _, props in rows),
                f'State outside property schema for {name}')
        default = facts['defaults'][name]
        require(default in {i for i, _ in rows}, f'Invalid default for {name}')
        base = gameplay[default]
        require(base['item'] == (name if name in items else 'minecraft:air'), f'Unexpected item mapping for {name}')
        block = dict(glass, id=block_id, name=name, item_id=items.get(name, 0),
                     translation_key=f"block.{name.replace(':', '.')}",
                     loot_table=f"create:blocks/{name.split(':', 1)[1]}" if name.split(':', 1)[1] in LOOT_BLOCKS else None,
                     spawn_floor_predicate=None, suffocation_predicate=None, default_state_id=default,
                     hardness=base['hardness'], blast_resistance=base['explosion_resistance'],
                     slipperiness=base['friction'], velocity_multiplier=base['speed_factor'],
                     jump_velocity_multiplier=base['jump_factor'],
                     properties=[shared[k] if k in shared else property_hash(properties, k, v)
                                 for k, v in schema.items()], states=[])
        for state_id, props in rows:
            row = gameplay[state_id]
            require(row['id'] == state_id, f'Gameplay state data mismatch at {state_id}')
            shape = [shape_id(box) for box in row['outline']]
            flags = sum(1 << bit for bit, field in ((2, 'requires_tool'), (3, 'shape_occlusion'),
                        (4, 'replaceable'), (5, 'liquid'), (7, 'full_collision'), (9, 'random_ticks'),
                        (10, 'solid_render'), (11, 'can_occlude')) if row[field])
            # shortcut: use cached outlines for partial collisions until the lab imports collision/side-support tables.
            block['states'].append(dict(glass['states'][0], id=state_id, properties=props,
                state_flags=flags | (64 if shape else 0) | (256 if row['solid_render'] else 0)
                    | (1 << 12 if name in {'create:speedometer', 'create:stressometer', 'create:item_drain', 'create:fluid_tank', 'create:blaze_burner', 'create:portable_storage_interface'} else 0),
                side_flags=255 if row['full_collision'] else 0,
                block_entity_type=entities[name] if name in implemented_entities and props.get('blaze') != 'none' else None,
                luminance=row['emission'], opacity=row['dampening'], piston_behavior=row['push'],
                hardness=row['hardness'], sound_type=sounds[row['sound']['break']['id'].removeprefix('minecraft:')],
                collision_shapes=[0] if row['full_collision'] else shape, outline_shapes=shape))
        require(name not in existing or existing[name]['id'] == block_id, f'Stale Create block ID {name}')
        vanilla.append(block)

    table['blocks'] = vanilla
    types = table['block_entity_types']
    types.extend([''] * (max(entities.values()) + 1 - len(types)))
    for name, index in entities.items():
        suffix = name.split(':', 1)[1]
        require(types[index] in ('', suffix) and suffix not in types[:index] + types[index + 1:],
                f'Block entity name or ID collision: {name}')
        types[index] = suffix
    for name, index in sorted(items.items(), key=lambda pair: pair[1]):
        row = {'id': index, 'components': item_components[name]}
        require(item_table.pop(name, row) == row, f'Stale Create item {name}')
        item_table[name] = row
    # Keep vanilla ordering, and serialize appended properties consistently after a three-block upgrade.
    used = {key for block in vanilla for key in block['properties']}
    added = [row for row in properties if row['enum_name'].startswith('create_') and row['hash_key'] in used]
    properties = [row for row in properties if not row['enum_name'].startswith('create_')]
    properties.extend(sorted(added, key=lambda row: row['hash_key']))
    return table, properties, item_table, blocks, items, states, entities


def install_mining_and_recipe_tags(assets, blocks, items):
    content = read_json(CONTENT_JSON)
    tag_dir = assets / 'datapack'
    block_tags = ('mineable/axe', 'mineable/pickaxe', 'needs_iron_tool', 'climbable')
    tags = {f'data/minecraft/tags/block/{name}.json': blocks for name in block_tags}
    tags.update({path: items for path in _extract_resources(content) if '/tags/item/' in path})
    for path, registry in tags.items():
        target = tag_dir / path
        source = json.loads(content[path])
        tag = read_json(target) if target.exists() else {'values': []}
        additions = [key for key in source['values'] if key in registry and key not in tag['values']]
        require(additions or any(key in registry for key in tag['values']), f'No known registry keys in {path}')
        if additions:
            tag['values'].extend(additions)
            target.parent.mkdir(parents=True, exist_ok=True)
            write_compact_json(target, tag)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pumpkin', type=Path, default=PUMPKIN)
    parser.add_argument('--client-cache', type=Path, default=CLIENT)
    args = parser.parse_args()
    assets = args.pumpkin / 'assets'
    table, properties, item_table, blocks, items, states, entities = generate(assets, args.client_cache)
    for path, value in (('blocks.json', table), ('properties.json', properties), ('items.json', item_table)):
        write_compact_json(assets / path, value)
    registry_items = {'minecraft:' + name if ':' not in name else name for name in item_table}
    install_mining_and_recipe_tags(assets, blocks, registry_items)
    content = read_json(CONTENT_JSON)
    modifier = json.loads(content['data/create/neoforge/biome_modifier/zinc_ore.json'])
    require((modifier['biomes'], modifier['features'], modifier['step']) ==
            ('#minecraft:is_overworld', 'create:zinc_ore', 'underground_ores'), 'Pinned zinc modifier changed')
    # Pumpkin's static codegen reads the minecraft directories. Only this internal feature name changes.
    worldgen = assets / 'datapack/data/minecraft/worldgen'
    ore = json.loads(content['data/create/worldgen/feature/zinc_ore.json'])
    placement = json.loads(content['data/create/worldgen/placed_feature/zinc_ore.json'])
    require(placement['feature'] == 'create:zinc_ore', 'Pinned zinc placement changed')
    placement['feature'] = 'minecraft:nextmc_create_zinc_ore'
    write_compact_json(worldgen / 'feature/nextmc_create_zinc_ore.json', ore)
    write_compact_json(worldgen / 'placed_feature/nextmc_create_zinc_ore.json', placement)
    recipes = [json.loads(data) for path, data in sorted(content.items())
               if path.startswith('data/create/recipe/item_application/') and path.endswith('.json')]
    require(len(recipes) == 6, 'Pinned Create item application recipe count changed')

    def item_names(key):
        if key.startswith('#'):
            ns, name = key[1:].split(':', 1)
            values = json.loads(content[f'data/{ns}/tags/item/{name}.json'])['values']
        else:
            values = [key]
        require(values and all(name in registry_items for name in values), f'Unknown item application ingredient: {key}')
        return values

    applications = []
    for recipe in recipes:
        block, held = recipe['ingredients']
        result, = recipe['results']
        for base in item_names(block):
            for tool in item_names(held):
                applications.append((base, tool, result['id'], not recipe.get('keepHeldItem', False)))
    require(len({(block, held) for block, held, _, _ in applications}) == len(applications), 'Ambiguous item application')
    write_compact_json(assets / 'nextmc-create-item-application.json', applications)
    mechanical = [json.loads(value) for path, value in content.items()
                  if path.startswith('data/create/recipe/mechanical_crafting/')]
    require(len(mechanical) == 1 and mechanical[0]['result'] == {'id': 'create:crushing_wheel', 'count': 2},
            'Pinned mechanical-crafting recipes changed')
    recipe, = mechanical
    recipe['key'] = {symbol: item_names(key) if key != '#minecraft:planks' else key
                     for symbol, key in recipe['key'].items()}
    write_compact_json(assets / 'nextmc-create-mechanical-crafting.json', recipe)
    milling = [json.loads(value) for path, value in sorted(content.items())
               if path.startswith('data/create/recipe/milling/') and path.endswith('.json')]
    require(len(milling) == 47, 'Pinned Create milling recipe count changed')
    write_compact_json(assets / 'nextmc-create-milling.json', milling)
    crushing = [json.loads(value) for path, value in sorted(content.items())
                if path.startswith('data/create/recipe/crushing/') and path.endswith('.json')]
    require(len(crushing) == 46, 'Pinned Create crushing recipe count changed')
    for recipe in crushing:
        ingredient, = recipe['ingredients']
        if ingredient.startswith('#') and ingredient != '#minecraft:wool':
            namespace, key = ingredient[1:].split(':', 1)
            names = json.loads(content[f'data/{namespace}/tags/item/{key}.json'])['values']
            require(names and all(isinstance(name, str) and not name.startswith('#') for name in names),
                    f'Expected a flat Create recipe tag: {ingredient}')
            recipe['ingredients'] = names
    write_compact_json(assets / 'nextmc-create-crushing.json', crushing)
    cutting = {f'create:{path.removeprefix("data/create/recipe/").removesuffix(".json")}': json.loads(value)
               for path, value in sorted(content.items())
               if path.startswith('data/create/recipe/cutting/') and path.endswith('.json')}
    require(len(cutting) == 143, 'Pinned Create cutting recipe count changed')
    write_compact_json(assets / 'nextmc-create-cutting.json', cutting)
    fan_tags = {path: json.loads(data) for path, data in content.items()
                if path.startswith(('data/create/tags/block/fan_processing_catalysts/',
                                    'data/create/tags/block/fan_transparent.json'))}
    require(len(fan_tags) == 4, 'Pinned Create fan tag count changed')
    for path, tag in fan_tags.items():
        target = assets / 'datapack' / path
        target.parent.mkdir(parents=True, exist_ok=True)
        write_compact_json(target, tag)
    fan_recipes = {kind: [dict(json.loads(content[path]), processing_time=0) for path in sorted(content)
                          if path.startswith(f'data/create/recipe/{kind}/')]
                   for kind in ('haunting', 'splashing')}
    require([len(rows) for rows in fan_recipes.values()] == [19, 15], 'Pinned Create fan recipe count changed')
    write_compact_json(assets / 'nextmc-create-fan.json', fan_recipes)
    basin_recipes = {}
    for kind in ('mixing', 'compacting'):
        rows = []
        for path, payload in sorted(content.items()):
            if not path.startswith(f'data/create/recipe/{kind}/'):
                continue
            row = json.loads(payload)
            if any(not isinstance(key, str) for key in row['ingredients']) or any('amount' in value for value in row['results']):
                continue  # Only the item-only transaction host is wired.
            def expand(key):
                if not key.startswith('#'):
                    return [key]
                namespace, tag = key[1:].split(':', 1)
                values = json.loads(content[f'data/{namespace}/tags/item/{tag}.json'])['values']
                require(values and all(isinstance(value, str) and not value.startswith('#') for value in values), key)
                return values
            rows.append(dict(row, ingredients=[expand(key) for key in row['ingredients']]))
        basin_recipes[kind] = rows
    require([len(rows) for rows in basin_recipes.values()] == [3, 1], 'Pinned item-only Basin recipe count changed')
    write_compact_json(assets / 'nextmc-create-basin.json', basin_recipes)
    (assets / 'nextmc-create-identity.bin').write_bytes(bytes.fromhex(WIRE_ID))
    print(f'{len(blocks)} Create blocks ({len(blocks.keys() & items.keys())} block items), '
          f'{sum(map(len, states.values()))} states, {len(items)} items, {len(entities)} block-entity type IDs')


if __name__ == '__main__':
    main()
