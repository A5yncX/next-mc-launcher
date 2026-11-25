import json
import tempfile
import unittest
from pathlib import Path

import generate_passive_data


BLOCKS = """andesite_alloy_block andesite_casing brass_block brass_casing copper_casing cut_andesite cut_andesite_bricks cut_diorite cut_diorite_bricks cut_granite cut_granite_bricks deepslate_zinc_ore industrial_iron_block layered_andesite polished_cut_andesite polished_cut_diorite polished_cut_granite raw_zinc_block small_andesite_bricks small_diorite_bricks small_granite_bricks weathered_iron_block zinc_block zinc_ore""".split()
RECIPES = """crafting/materials/andesite_alloy_block.json crafting/materials/brass_block_from_compacting.json crafting/materials/raw_zinc_block.json crafting/materials/zinc_block_from_compacting.json cut_andesite_bricks_from_stone_types_andesite_stonecutting.json cut_andesite_from_stone_types_andesite_stonecutting.json cut_diorite_bricks_from_stone_types_diorite_stonecutting.json cut_diorite_from_stone_types_diorite_stonecutting.json cut_granite_bricks_from_stone_types_granite_stonecutting.json cut_granite_from_stone_types_granite_stonecutting.json industrial_iron_block_from_ingots_iron_stonecutting.json layered_andesite_from_stone_types_andesite_stonecutting.json polished_cut_andesite_from_stone_types_andesite_stonecutting.json polished_cut_diorite_from_stone_types_diorite_stonecutting.json polished_cut_granite_from_stone_types_granite_stonecutting.json small_andesite_bricks_from_stone_types_andesite_stonecutting.json small_diorite_bricks_from_stone_types_diorite_stonecutting.json small_granite_bricks_from_stone_types_granite_stonecutting.json weathered_iron_block_from_ingots_iron_stonecutting.json""".split()
TAGS = """data/c/tags/item/ingots/brass.json data/c/tags/item/ingots/iron.json data/c/tags/item/ingots/zinc.json data/create/tags/item/stone_types/andesite.json data/create/tags/item/stone_types/diorite.json data/create/tags/item/stone_types/granite.json""".split()


class PassiveDataGeneratorTests(unittest.TestCase):
    def test_pinned_export_generates_exact_pack_inventory(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "passive-pack"
            counts = generate_passive_data.generate(output)
            second_output = Path(temporary) / "passive-pack-repeat"
            generate_passive_data.generate(second_output)

            files = {path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file()}
            expected = {f"data/create/loot_table/blocks/{name}.json"
                        for name in (*BLOCKS, 'water_wheel', 'large_water_wheel', 'water_wheel_structure', 'depot',
                                     'hand_crank', 'encased_chain_drive', 'adjustable_chain_gearshift', 'mechanical_press', 'item_drain', 'fluid_tank', 'fluid_pipe', 'fluid_valve', 'mechanical_pump',
                                     'chute', 'smart_chute', 'millstone', 'encased_fan', 'mechanical_drill', 'mechanical_saw', 'crushing_wheel', 'sticker', 'blaze_burner', 'lit_blaze_burner', 'basin', 'mechanical_mixer', 'andesite_funnel', 'brass_funnel', 'gantry_carriage', 'gantry_shaft', 'belt', 'mechanical_piston', 'sticky_mechanical_piston', 'piston_extension_pole', 'rope_pulley', 'mechanical_piston_head', 'rope', 'pulley_magnet', 'deployer', 'mechanical_crafter', 'speedometer', 'stressometer', 'portable_storage_interface', *generate_passive_data.ENCASED_BLOCKS, *generate_passive_data.SAIL_BLOCKS)}
            expected |= {f"data/create/recipe/{name}" for name in (*RECIPES,
                         'crafting/kinetics/speedometer.json',
                         'crafting/kinetics/speedometer_from_conversion.json',
                         'crafting/kinetics/stressometer_from_conversion.json',
                         'crafting/kinetics/portable_storage_interface.json')}
            expected |= {f"data/create/recipe/{stone}_from_stone_types_{stone}_stonecutting.json"
                         for stone in ('andesite', 'diorite', 'granite')}
            expected |= set(TAGS)
            expected.add("pack.mcmeta")
            self.assertEqual(files, expected)
            self.assertEqual(counts, (89, 26, 6))
            for name in ('speedometer', 'stressometer'):
                loot = json.loads((output / f"data/create/loot_table/blocks/{name}.json").read_text())
                self.assertEqual(loot['pools'], [{'rolls': 1, 'entries': [{'type': 'minecraft:item', 'name': f'create:{name}'}]}])
            for name in generate_passive_data.SAIL_BLOCKS:
                loot = json.loads((output / f"data/create/loot_table/blocks/{name}.json").read_text())
                self.assertEqual(loot['pools'][0]['entries'][0]['name'],
                                 'create:sail_frame' if name == 'sail_frame' else 'create:white_sail')
            self.assertEqual(
                {
                    path.relative_to(output): path.read_bytes()
                    for path in output.rglob("*")
                    if path.is_file()
                },
                {
                    path.relative_to(second_output): path.read_bytes()
                    for path in second_output.rglob("*")
                    if path.is_file()
                },
            )

            metadata = json.loads((output / "pack.mcmeta").read_text(encoding="utf-8"))
            self.assertEqual(metadata["pack"]["min_format"], 121)
            self.assertEqual(metadata["pack"]["max_format"], 121)

    def test_existing_nonempty_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "existing-pack"
            output.mkdir()
            marker = output / "keep.txt"
            marker.write_text("preserve", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                generate_passive_data.generate(output)

            self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")


if __name__ == "__main__":
    unittest.main()
