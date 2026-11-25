#!/usr/bin/env python3
"""Add the pinned Create motor/shaft/cogwheel registry data to Pumpkin assets."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUMPKIN = ROOT / ".cache/Pumpkin-eda69440e6369c5f8a05c3f69fc809c40dab93a6"
CLIENT = (
    ROOT
    / ".cache/create-join-gmrguli6/client/.horizon-cache/mod-content/b00d2fb9c5fc1384"
)

AXIS = -1559386812
WATERLOGGED = -1075111154
FACING = 1571391763

BLOCKS = (
    {
        "name": "create:cogwheel",
        "block_id": 1308,
        "item_id": 1684,
        "block_entity_id": 71,
        "state_ids": tuple(range(36340, 36346)),
        "properties": (AXIS, WATERLOGGED),
        "state_properties": tuple(
            {"axis": axis, "waterlogged": waterlogged}
            for axis in ("y", "z", "x")
            for waterlogged in ("false", "true")
        ),
    },
    {
        "name": "create:creative_motor",
        "block_id": 1310,
        "item_id": 1690,
        "block_entity_id": 73,
        "state_ids": tuple(range(36347, 36353)),
        "properties": (FACING,),
        "state_properties": tuple(
            {"facing": facing}
            for facing in ("north", "south", "east", "west", "up", "down")
        ),
    },
    {
        "name": "create:shaft",
        "block_id": 1375,
        "item_id": 1759,
        "block_entity_id": 138,
        "state_ids": tuple(range(37740, 37746)),
        "properties": (AXIS, WATERLOGGED),
        "state_properties": tuple(
            {"axis": axis, "waterlogged": waterlogged}
            for axis in ("y", "z", "x")
            for waterlogged in ("false", "true")
        ),
    },
)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_compact_json(path: Path, value) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def registry_id(registries: dict, registry: str, name: str) -> int:
    return registries[registry]["entries"][name]["protocol_id"]


def verify_client_data(assets: Path, client: Path) -> tuple[dict, dict, dict]:
    facts = read_json(client / "facts.json")
    registries = read_json(client / "registries.json")
    client_items = read_json(client / "items.json")
    properties = read_json(assets / "properties.json")
    property_hashes = {entry["hash_key"] for entry in properties}
    required_hashes = {AXIS, WATERLOGGED, FACING}
    if not required_hashes <= property_hashes:
        raise ValueError("Pumpkin properties.json is missing a Create block property")
    states = facts["states"]

    for spec in BLOCKS:
        name = spec["name"]
        expected_ids = {
            "minecraft:block": spec["block_id"],
            "minecraft:item": spec["item_id"],
            "minecraft:block_entity_type": spec["block_entity_id"],
        }
        for registry, expected in expected_ids.items():
            actual = registry_id(registries, registry, name)
            if actual != expected:
                raise ValueError(f"{registry} ID for {name}: expected {expected}, got {actual}")

        rows = [(state_id, state) for state_id, state in enumerate(states) if state[0] == name]
        actual_ids = tuple(state_id for state_id, _ in rows)
        if actual_ids != spec["state_ids"]:
            raise ValueError(f"Unexpected state IDs for {name}: {actual_ids}")
        if facts["defaults"].get(name) != spec["state_ids"][0]:
            raise ValueError(f"Unexpected default state ID for {name}")
        actual_properties = tuple(state[-1].get("properties", {}) for _, state in rows)
        if actual_properties != spec["state_properties"]:
            raise ValueError(f"Unexpected state property order for {name}: {actual_properties}")
        if name not in client_items:
            raise ValueError(f"Pinned client item components are missing for {name}")

    return facts, registries, client_items


def exported_data_digest(facts: dict, registries: dict) -> bytes:
    def sized(value: bytes) -> bytes:
        return len(value).to_bytes(8, "little") + value

    digest = hashlib.sha256()
    for row in facts["states"]:
        state = row[4]
        ordered = {"id": state["id"]}
        if state.get("properties") is not None:
            ordered["properties"] = dict(sorted(state["properties"].items()))
        digest.update(sized(json.dumps(ordered, ensure_ascii=False, separators=(",", ":")).encode()))
    fingerprint = digest.digest()
    # Include the exported state and mod registry IDs; the binary's wire identity is pinned separately.
    for key in ("item", "mob_effect", "fluid", "entity_type", "menu"):
        registry = f"minecraft:{key}"
        entries = sorted(
            (row["protocol_id"], name)
            for name, row in registries.get(registry, {}).get("entries", {}).items()
            if not name.startswith("minecraft:")
        )
        if entries:
            digest = hashlib.sha256(fingerprint + sized(registry.encode()))
            for index, name in entries:
                digest.update(index.to_bytes(8, "little") + sized(name.encode()))
            fingerprint = digest.digest()
    return fingerprint


def create_block(spec: dict, glass: dict) -> dict:
    block = copy.deepcopy(glass)
    block.update(
        {
            "id": spec["block_id"],
            "name": spec["name"],
            "translation_key": f"block.{spec['name'].replace(':', '.')}",
            "item_id": spec["item_id"],
            "loot_table": None,
            "spawn_floor_predicate": None,
            "suffocation_predicate": None,
            "properties": list(spec["properties"]),
            "default_state_id": spec["state_ids"][0],
            "states": [],
        }
    )
    # The client export has no collision/mining extraction; glass supplies a transparent, non-occluding baseline.
    glass_state = glass["states"][0]
    for state_id, state_properties in zip(spec["state_ids"], spec["state_properties"], strict=True):
        state = copy.deepcopy(glass_state)
        state["id"] = state_id
        state["block_entity_type"] = spec["block_entity_id"]
        state["properties"] = state_properties
        block["states"].append(state)
    return block


def add_blocks(assets: dict, facts: dict) -> bool:
    blocks = assets["blocks"]
    names = {block["name"]: block for block in blocks}
    ids = {block["id"] for block in blocks}
    item_ids = {block["item_id"] for block in blocks}
    state_ids = {state["id"] for block in blocks for state in block["states"]}
    if len(names) != len(blocks) or len(ids) != len(blocks):
        raise ValueError("Existing block assets contain duplicate names or IDs")

    if any(name in names for name in (spec["name"] for spec in BLOCKS)):
        # Only exact re-runs are accepted; stale or hand-edited entries need an explicit review.
        glass = names.get("glass")
        if glass is None:
            raise ValueError("Cannot validate existing Create blocks without the glass baseline")
        for spec in BLOCKS:
            expected = create_block(spec, glass)
            if spec["name"] in names and names[spec["name"]] != expected:
                raise ValueError(f"Existing block entry differs from generated data: {spec['name']}")
        if any(spec["name"] not in names for spec in BLOCKS):
            raise ValueError("Partial Create block data found; refusing to append a mixed dataset")
        return False

    glass = names.get("glass")
    if glass is None:
        raise ValueError("Vanilla glass baseline is missing")
    for spec in BLOCKS:
        if spec["block_id"] in ids or spec["item_id"] in item_ids:
            raise ValueError(f"Create IDs collide with existing block data: {spec['name']}")
        if state_ids.intersection(spec["state_ids"]):
            raise ValueError(f"Create state IDs collide with existing block data: {spec['name']}")
        for state_id in spec["state_ids"]:
            if facts["states"][state_id][0] != spec["name"]:
                raise ValueError(f"Pinned facts do not match state ID {state_id}")
        blocks.append(create_block(spec, glass))
        ids.add(spec["block_id"])
        item_ids.add(spec["item_id"])
        state_ids.update(spec["state_ids"])
    return True


def add_block_entity_types(assets: dict) -> bool:
    types = assets["block_entity_types"]
    original_prefix = types[:]
    needed = max(spec["block_entity_id"] for spec in BLOCKS) + 1
    types.extend([""] * (needed - len(types)))
    for spec in BLOCKS:
        index = spec["block_entity_id"]
        suffix = spec["name"].rsplit(":", 1)[1]
        if types[index] not in ("", suffix):
            raise ValueError(f"Block-entity type ID {index} is already assigned to {types[index]!r}")
        types[index] = suffix
    return types != original_prefix


def add_items(path: Path, client_items: dict, registries: dict) -> str | None:
    original = path.read_text(encoding="utf-8")
    items = json.loads(original)
    existing_ids = {item["id"] for item in items.values()}
    additions = []
    for spec in BLOCKS:
        name = spec["name"]
        item_id = registry_id(registries, "minecraft:item", name)
        entry = {"id": item_id, "components": client_items[name]}
        if name in items:
            if items[name] != entry:
                raise ValueError(f"Existing item entry differs from pinned data: {name}")
            continue
        if item_id in existing_ids:
            raise ValueError(f"Create item ID collides with existing item data: {name} ({item_id})")
        additions.append((name, entry))
        existing_ids.add(item_id)

    if not additions:
        return None
    if any(name in items for name in (spec["name"] for spec in BLOCKS)):
        raise ValueError("Partial Create item data found; refusing to append a mixed dataset")

    insert_at = original.rfind("}")
    if insert_at < 0 or original[insert_at + 1 :].strip():
        raise ValueError(f"Unexpected top-level JSON layout in {path}")
    prefix = original[:insert_at]
    separator = "" if prefix.rstrip().endswith("{") else ","
    encoded = ",".join(
        json.dumps(name, ensure_ascii=False)
        + ":"
        + json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
        for name, entry in additions
    )
    return prefix + separator + encoded + original[insert_at:]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pumpkin", type=Path, default=PUMPKIN, help="unpacked pinned Pumpkin source")
    parser.add_argument("--client-cache", type=Path, default=CLIENT, help="pinned Create-enabled mod-content cache folder")
    args = parser.parse_args()
    assets = args.pumpkin / "assets"
    facts, registries, client_items = verify_client_data(assets, args.client_cache)
    digest = exported_data_digest(facts, registries).hex()
    if digest != "06d8f0d5bbe6db6d879e44426a8a8236a033594df7d496a2e50fe22fa3005928":
        raise ValueError(f"Unexpected pinned Horizon registry data: {digest}")
    # Verified against the actual beta.2 Create-enabled binary, not inferred from exported JSON.
    fingerprint = bytes.fromhex("759a0d8edbe01d868a554e8fe0a9025ed8fa93c6c9aa274348f066d755d4d37b")

    blocks_path, items_path = assets / "blocks.json", assets / "items.json"
    blocks = read_json(blocks_path)
    block_data_changed = add_blocks(blocks, facts)
    be_types_changed = add_block_entity_types(blocks)
    items_output = add_items(items_path, client_items, registries)
    (assets / "nextmc-create-identity.bin").write_bytes(fingerprint)
    print(f"Create registry identity: {fingerprint.hex()}")
    if block_data_changed or be_types_changed:
        write_compact_json(blocks_path, blocks)
    if items_output is not None:
        items_path.write_text(items_output, encoding="utf-8")
    print(
        "Create registry data is up to date"
        if not (block_data_changed or be_types_changed or items_output is not None)
        else "Added Create creative_motor, shaft, and cogwheel data"
    )


if __name__ == "__main__":
    main()
