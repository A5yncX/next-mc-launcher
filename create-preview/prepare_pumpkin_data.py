"""Extract the pinned local server datapack before compiling the patched Pumpkin tree."""
from io import BytesIO
from pathlib import Path
import shutil
import sys
from zipfile import ZipFile


def prepare(tree: Path, server_jar: Path):
    assets = tree / 'assets'
    target = assets / 'datapack'
    if (target / 'data/minecraft').exists():
        raise FileExistsError(f'Use a clean Pumpkin source tree: {target / "data/minecraft"}')
    with ZipFile(server_jar) as jar:
        with ZipFile(BytesIO(jar.read('META-INF/versions/26.3/server-26.3.jar'))) as inner:
            files = [entry for entry in inner.namelist() if entry.startswith('data/')]
            if 'data/minecraft/tags/block/mineable/pickaxe.json' not in files:
                raise ValueError('Expected a Minecraft 26.3 server datapack')
            inner.extractall(target, members=files)
    shutil.copytree(assets / 'conventional_tags/data/c', target / 'data/c', dirs_exist_ok=True)


if __name__ == '__main__':
    prepare(Path(sys.argv[1]), Path(sys.argv[2]))
