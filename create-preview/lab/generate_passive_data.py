#!/usr/bin/env python3
"""Extract the pinned passive-material loot, vanilla recipes, and recipe tags."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTENT_JSON = (
    ROOT
    / "research_create_rust/.create-lab-build/stage/native-data/create/content.json"
)

PASSIVE_BLOCKS = (
    "andesite_alloy_block",
    "andesite_casing",
    "brass_block",
    "brass_casing",
    "copper_casing",
    "cut_andesite",
    "cut_andesite_bricks",
    "cut_diorite",
    "cut_diorite_bricks",
    "cut_granite",
    "cut_granite_bricks",
    "deepslate_zinc_ore",
    "industrial_iron_block",
    "layered_andesite",
    "polished_cut_andesite",
    "polished_cut_diorite",
    "polished_cut_granite",
    "raw_zinc_block",
    "small_andesite_bricks",
    "small_diorite_bricks",
    "small_granite_bricks",
    "weathered_iron_block",
    "zinc_block",
    "zinc_ore",
)

SAIL_BLOCKS = ("sail_frame", *(f"{color}_sail" for color in (
    "white", "orange", "magenta", "light_blue", "yellow", "lime", "pink", "gray", "light_gray",
    "cyan", "purple", "blue", "brown", "green", "red", "black",
)))
ENCASED_BLOCKS = tuple(f"{casing}_encased_{part}" for casing in ("andesite", "brass")
                       for part in ("shaft", "cogwheel", "large_cogwheel"))

LOOT_BLOCKS = (*PASSIVE_BLOCKS, *ENCASED_BLOCKS, "water_wheel", "large_water_wheel", "water_wheel_structure", "depot",
               "hand_crank", "encased_chain_drive", "adjustable_chain_gearshift", "mechanical_press", "item_drain", "fluid_tank", "fluid_pipe", "fluid_valve", "mechanical_pump",
               "chute", "smart_chute", "millstone", "encased_fan", "mechanical_drill", "mechanical_saw", "crushing_wheel", "sticker", "blaze_burner", "lit_blaze_burner", "basin", "mechanical_mixer", "andesite_funnel", "belt", "brass_funnel", "gantry_carriage", "gantry_shaft", "mechanical_piston", "sticky_mechanical_piston", "piston_extension_pole", "rope_pulley", "mechanical_piston_head", "rope", "pulley_magnet", "deployer", "mechanical_crafter", "speedometer", "stressometer", "portable_storage_interface", *SAIL_BLOCKS)

GAUGE_RECIPES = {
    "crafting/kinetics/speedometer.json": ("minecraft:crafting_shaped", "create:speedometer"),
    "crafting/kinetics/speedometer_from_conversion.json": ("minecraft:crafting_shapeless", "create:speedometer"),
    "crafting/kinetics/stressometer_from_conversion.json": ("minecraft:crafting_shapeless", "create:stressometer"),
}

# Exact source paths, expected vanilla recipe types, and output IDs for this pinned export.
EXPECTED_RECIPES = {
    **{f"data/create/recipe/{path}": schema for path, schema in GAUGE_RECIPES.items()},
    "data/create/recipe/crafting/kinetics/portable_storage_interface.json": (
        "minecraft:crafting_shapeless", "create:portable_storage_interface",
    ),
    "data/create/recipe/crafting/materials/andesite_alloy_block.json": (
        "minecraft:crafting_shaped",
        "create:andesite_alloy_block",
    ),
    "data/create/recipe/crafting/materials/brass_block_from_compacting.json": (
        "minecraft:crafting_shaped",
        "create:brass_block",
    ),
    "data/create/recipe/crafting/materials/raw_zinc_block.json": (
        "minecraft:crafting_shaped",
        "create:raw_zinc_block",
    ),
    "data/create/recipe/crafting/materials/zinc_block_from_compacting.json": (
        "minecraft:crafting_shaped",
        "create:zinc_block",
    ),
    "data/create/recipe/andesite_from_stone_types_andesite_stonecutting.json": (
        "minecraft:stonecutting", "minecraft:andesite",
    ),
    "data/create/recipe/diorite_from_stone_types_diorite_stonecutting.json": (
        "minecraft:stonecutting", "minecraft:diorite",
    ),
    "data/create/recipe/granite_from_stone_types_granite_stonecutting.json": (
        "minecraft:stonecutting", "minecraft:granite",
    ),
    "data/create/recipe/cut_andesite_bricks_from_stone_types_andesite_stonecutting.json": (
        "minecraft:stonecutting",
        "create:cut_andesite_bricks",
    ),
    "data/create/recipe/cut_andesite_from_stone_types_andesite_stonecutting.json": (
        "minecraft:stonecutting",
        "create:cut_andesite",
    ),
    "data/create/recipe/cut_diorite_bricks_from_stone_types_diorite_stonecutting.json": (
        "minecraft:stonecutting",
        "create:cut_diorite_bricks",
    ),
    "data/create/recipe/cut_diorite_from_stone_types_diorite_stonecutting.json": (
        "minecraft:stonecutting",
        "create:cut_diorite",
    ),
    "data/create/recipe/cut_granite_bricks_from_stone_types_granite_stonecutting.json": (
        "minecraft:stonecutting",
        "create:cut_granite_bricks",
    ),
    "data/create/recipe/cut_granite_from_stone_types_granite_stonecutting.json": (
        "minecraft:stonecutting",
        "create:cut_granite",
    ),
    "data/create/recipe/industrial_iron_block_from_ingots_iron_stonecutting.json": (
        "minecraft:stonecutting",
        "create:industrial_iron_block",
    ),
    "data/create/recipe/layered_andesite_from_stone_types_andesite_stonecutting.json": (
        "minecraft:stonecutting",
        "create:layered_andesite",
    ),
    "data/create/recipe/polished_cut_andesite_from_stone_types_andesite_stonecutting.json": (
        "minecraft:stonecutting",
        "create:polished_cut_andesite",
    ),
    "data/create/recipe/polished_cut_diorite_from_stone_types_diorite_stonecutting.json": (
        "minecraft:stonecutting",
        "create:polished_cut_diorite",
    ),
    "data/create/recipe/polished_cut_granite_from_stone_types_granite_stonecutting.json": (
        "minecraft:stonecutting",
        "create:polished_cut_granite",
    ),
    "data/create/recipe/small_andesite_bricks_from_stone_types_andesite_stonecutting.json": (
        "minecraft:stonecutting",
        "create:small_andesite_bricks",
    ),
    "data/create/recipe/small_diorite_bricks_from_stone_types_diorite_stonecutting.json": (
        "minecraft:stonecutting",
        "create:small_diorite_bricks",
    ),
    "data/create/recipe/small_granite_bricks_from_stone_types_granite_stonecutting.json": (
        "minecraft:stonecutting",
        "create:small_granite_bricks",
    ),
    "data/create/recipe/weathered_iron_block_from_ingots_iron_stonecutting.json": (
        "minecraft:stonecutting",
        "create:weathered_iron_block",
    ),
}

PACK_METADATA = {
    "pack": {
        "description": "Create passive-material lab data for Minecraft 26.3",
        "min_format": 121,
        "max_format": 121,
    }
}


def _validate_resource_path(resource: str) -> None:
    parts = resource.split("/")
    if (
        not resource.startswith("data/")
        or "\\" in resource
        or any(part in ("", ".", "..") for part in parts)
    ):
        raise ValueError(f"Unsafe resource path: {resource!r}")


def _source_json(content: dict, resource: str) -> tuple[str, dict]:
    raw = content.get(resource)
    if not isinstance(raw, str):
        raise ValueError(f"Missing serialized source resource: {resource}")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in source resource {resource}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"Expected a JSON object in source resource: {resource}")
    return raw, parsed


def _result_id(recipe: dict) -> str | None:
    result = recipe.get("result")
    return result.get("id") if isinstance(result, dict) else None


def _recipe_tag_references(recipe: dict):
    match recipe.get("type"):
        case "minecraft:crafting_shaped":
            ingredients = recipe.get("key", {}).values()
        case "minecraft:crafting_shapeless":
            ingredients = recipe.get("ingredients", ())
        case _:
            ingredients = (recipe.get("ingredient"),)

    def walk(value):
        if isinstance(value, str):
            if value.startswith("#"):
                yield value[1:]
        elif isinstance(value, dict):
            for nested in value.values():
                yield from walk(nested)
        elif isinstance(value, list):
            for nested in value:
                yield from walk(nested)

    for ingredient in ingredients:
        yield from walk(ingredient)


def _tag_resource_path(reference: str) -> str:
    namespace, separator, tag_path = reference.partition(":")
    if not separator:
        namespace, tag_path = "minecraft", namespace
    resource = f"data/{namespace}/tags/item/{tag_path}.json"
    _validate_resource_path(resource)
    return resource


def _extract_resources(content: dict) -> dict[str, str]:
    if not isinstance(content, dict):
        raise ValueError("Pinned content.json must contain a resource-path mapping")

    resources: dict[str, str] = {}
    for block in LOOT_BLOCKS:
        resource = f"data/create/loot_table/blocks/{block}.json"
        _validate_resource_path(resource)
        raw, _ = _source_json(content, resource)
        resources[resource] = raw

    passive_items = {f"create:{block}" for block in PASSIVE_BLOCKS}
    selected = {}
    for resource in sorted(content):
        if not resource.startswith("data/create/recipe/") or not resource.endswith(".json"):
            continue
        raw, recipe = _source_json(content, resource)
        if (
            resource in EXPECTED_RECIPES
            or (recipe.get("type") in {"minecraft:crafting_shaped", "minecraft:stonecutting"}
                and _result_id(recipe) in passive_items)
        ):
            selected[resource] = (raw, recipe)

    if set(selected) != set(EXPECTED_RECIPES):
        missing = sorted(set(EXPECTED_RECIPES) - set(selected))
        extra = sorted(set(selected) - set(EXPECTED_RECIPES))
        raise ValueError(f"Passive vanilla recipe inventory mismatch; missing={missing}, extra={extra}")

    tag_paths = set()
    for resource, (raw, recipe) in sorted(selected.items()):
        _validate_resource_path(resource)
        expected_type, expected_result = EXPECTED_RECIPES[resource]
        if recipe.get("type") != expected_type or _result_id(recipe) != expected_result:
            raise ValueError(f"Unexpected recipe schema or result in {resource}")
        result = recipe.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("count"), int) or result["count"] < 1:
            raise ValueError(f"Invalid vanilla recipe result in {resource}")
        if expected_type == "minecraft:crafting_shaped":
            pattern, key = recipe.get("pattern"), recipe.get("key")
            if (
                not isinstance(pattern, list)
                or not pattern
                or not all(isinstance(row, str) for row in pattern)
                or not isinstance(key, dict)
                or not key
            ):
                raise ValueError(f"Invalid shaped recipe schema in {resource}")
        if expected_type == "minecraft:crafting_shapeless":
            ingredients = recipe.get("ingredients")
            if not isinstance(ingredients, list) or not ingredients or not all(
                isinstance(item, (str, dict, list)) for item in ingredients
            ):
                raise ValueError(f"Invalid shapeless recipe schema in {resource}")
        if expected_type == "minecraft:stonecutting" and not isinstance(
            recipe.get("ingredient"), (str, dict)
        ):
            raise ValueError(f"Invalid stonecutting ingredient in {resource}")
        resources[resource] = raw
        tag_paths.update(_tag_resource_path(ref) for ref in _recipe_tag_references(recipe))

    for resource in sorted(tag_paths):
        _validate_resource_path(resource)
        raw, tag = _source_json(content, resource)
        if not isinstance(tag.get("values"), list):
            raise ValueError(f"Invalid item tag schema in {resource}")
        resources[resource] = raw

    return resources


def generate(output: Path) -> tuple[int, int, int]:
    content = json.loads(CONTENT_JSON.read_text(encoding="utf-8"))
    resources = _extract_resources(content)

    output = Path(output)
    if output.is_symlink():
        raise FileExistsError(f"Refusing to write through a symlink: {output}")
    if output.exists():
        if not output.is_dir() or any(output.iterdir()):
            raise FileExistsError(f"Output must be a new or empty directory: {output}")
    else:
        output.mkdir(parents=True)

    for resource, raw in sorted(resources.items()):
        path = output.joinpath(*resource.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(raw)
            if not raw.endswith("\n"):
                stream.write("\n")

    (output / "pack.mcmeta").write_text(
        json.dumps(PACK_METADATA, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    loot_count = len(LOOT_BLOCKS)
    recipe_count = len(EXPECTED_RECIPES)
    tag_count = len(resources) - loot_count - recipe_count
    return loot_count, recipe_count, tag_count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="new or empty directory for the datapack root")
    args = parser.parse_args()
    loot_count, recipe_count, tag_count = generate(args.output)
    print(
        f"Wrote {loot_count} loot tables, {recipe_count} recipes, and {tag_count} ingredient tags to {args.output}"
    )


if __name__ == "__main__":
    main()
