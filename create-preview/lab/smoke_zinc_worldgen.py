"""Compare natural zinc in fresh seed-101 worlds and verify the saved blocks in two Horizon clients."""
import argparse
import asyncio
from collections import Counter
from pathlib import Path
import socket
import sys
import tempfile
from types import SimpleNamespace

from smoke_core import CONFIG, DATA, HERE, ROOT, server
from smoke_placement import client, state_on

sys.path.insert(0, str(ROOT / 'research_create_rust/.create-lab-build/stage/tools'))
from anvil_dump import region_chunks

ORES = {'create:zinc_ore': {'minecraft:stone', 'minecraft:granite', 'minecraft:diorite', 'minecraft:andesite'},
        'create:deepslate_zinc_ore': {'minecraft:deepslate', 'minecraft:tuff'}}


def regions(room):
    chunks = {}
    for path in (room / 'create-lab/dimensions/minecraft/overworld/region').glob('r.*.*.mca'):
        for chunk in region_chunks(path).values():
            chunks[chunk['xPos'], chunk['zPos']] = {s['Y'][1]: s.get('block_states') for s in chunk['sections']}
    assert chunks, f'no saved Anvil chunks in {room}'
    return chunks


def at(states, index):
    if not states:
        return 'minecraft:air'
    palette = states['palette']
    if len(palette) == 1:
        return palette[0]['Name']
    bits = max(4, (len(palette) - 1).bit_length())
    per_long = 64 // bits
    loc = (states['data'][1][index // per_long] >> ((index % per_long) * bits)) & ((1 << bits) - 1)
    return palette[loc]['Name']


async def generate(args, room, name):
    room.mkdir()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    (room / 'pumpkin.toml').write_text(CONFIG.format(port=port) +
        '\n[world.chunk]\ntype = "anvil"\n[world.chunk.compression]\nalgorithm = "ZLib"\nlevel = 6\n')
    async with server(args, room, port, name):
        async with client(args, room, port, 'Builder'):
            await asyncio.sleep(5)
    return port


async def test(args, room):
    before, after = room / 'baseline', room / 'zinc'
    await generate(SimpleNamespace(**{**vars(args), 'pumpkin': args.baseline}), before, 'baseline')
    port = await generate(args, after, 'zinc')
    vanilla, created = regions(before), regions(after)
    counts, matching, examples = Counter(), Counter(), {}
    for chunk_pos, sections in created.items():
        if chunk_pos not in vanilla:
            continue
        for sy, states in sections.items():
            if not states or not any(s['Name'] in ORES for s in states['palette']):
                continue
            for i in range(4096):
                ore = at(states, i)
                if ore not in ORES:
                    continue
                x, y, z = chunk_pos[0] * 16 + (i & 15), sy * 16 + (i >> 8), chunk_pos[1] * 16 + ((i >> 4) & 15)
                old = at(vanilla[chunk_pos].get(sy), i)
                assert -64 <= y <= 70, (ore, (x, y, z), old)
                counts[ore] += 1
                if old in ORES[ore]:
                    matching[ore] += 1
                    pos = (x, y, z)
                    distance = (x + 264) ** 2 + (z + 109) ** 2
                    if ore not in examples or distance < examples[ore][0]:
                        examples[ore] = (distance, pos)
    assert set(counts) == set(ORES) and all(n > 8 for n in counts.values()), counts
    # Final vanilla terrain has later decorations and overlapping neighbor features; it is not the pre-ore state.
    assert all(matching[ore] >= .98 * count for ore, count in counts.items()), (counts, matching)
    print(f'PASS: seed 101 saves both natural ores; baseline rock matches {dict(matching)} of {dict(counts)}', flush=True)
    reconnect = after / 'reconnect'
    reconnect.mkdir()
    async with server(args, after, port, 'restart'):
        async with client(args, reconnect, port, 'Builder') as (b, _), client(args, reconnect, port, 'Witness') as (w, _):
            for ore, (distance, pos) in examples.items():
                assert distance <= 16 ** 2, (ore, pos)
                for call in (b, w):
                    await state_on(call, pos, ore)
    print('PASS: both Horizon clients see both natural zinc variants after reload', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', type=Path, default=ROOT / 'research_create_rust/.create-lab-build/game-target/fast/horizon-client.exe')
    parser.add_argument('--pumpkin', type=Path, default=HERE.parent / '.cache/core-target/debug/pumpkin.exe')
    parser.add_argument('--resources', type=Path, default=DATA / 'resources-create-v4')
    parser.add_argument('--create-jar', type=Path)
    parser.add_argument('--baseline', type=Path, required=True, help='same server build before the zinc feature')
    args = parser.parse_args()
    for attr, path in vars(args).items():
        if path is not None:
            setattr(args, attr, path.resolve(strict=True))
    room = Path(tempfile.mkdtemp(prefix='create-zinc-', dir=HERE.parent / '.cache'))
    print(f'Logs: {room}', flush=True)
    asyncio.run(test(args, room))
