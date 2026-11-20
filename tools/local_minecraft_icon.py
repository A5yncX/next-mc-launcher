"""Generate local-only Windows icon resources from Minecraft's installed asset index."""

import argparse
import hashlib
import json
import struct
from pathlib import Path


def resource(kind, number, data):
    return (
        struct.pack('<IIHHHHIHHII', len(data), 32, 0xffff, kind, 0xffff, number,
                    0, 0x1030 if kind else 0, 0, 0, 0)
        + data + b'\0' * (-len(data) % 4)
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('assets', type=Path, help='Minecraft assets directory')
    parser.add_argument('output', type=Path, help='Local output directory (not for redistribution)')
    args = parser.parse_args()
    index = json.loads((args.assets / 'indexes/34.json').read_bytes())['objects']
    entries = []
    images = []
    for size in (16, 32, 48, 128, 256):
        asset = index[f'icons/icon_{size}x{size}.png']
        digest = asset['hash']
        image = (args.assets / 'objects' / digest[:2] / digest).read_bytes()
        if hashlib.sha1(image).hexdigest() != digest or len(image) != asset['size']:
            raise ValueError(f'Minecraft icon {size}x{size} does not match the asset index')
        if image[:8] != b'\x89PNG\r\n\x1a\n' or struct.unpack('>II', image[16:24]) != (size, size):
            raise ValueError(f'Minecraft icon {size}x{size} is not the expected PNG')
        images.append(image)
        entries.append(struct.pack('<BBBBHHIH', size % 256, size % 256, 0, 0, 1, 32,
                                   len(image), len(images)))
    group = struct.pack('<HHH', 0, 1, len(images)) + b''.join(entries)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'minecraft-icon.res').write_bytes(
        resource(0, 0, b'') + resource(14, 1, group)
        + b''.join(resource(3, i, image) for i, image in enumerate(images, 1))
    )
    (args.output / 'minecraft-icon-32.png').write_bytes(images[1])


if __name__ == '__main__':
    main()
