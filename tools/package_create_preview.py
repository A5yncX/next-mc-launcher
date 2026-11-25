"""Package the tested Rust Create preview from the local research build and pinned beta.2 inputs."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

import package_windows as portable
from release_windows import checksum, pin

ROOT = portable.LAUNCHER.parent
DOCS = portable.LAUNCHER / 'create-preview'
LAB = ROOT / 'research_pumpkin_horizon/create-core'
CACHE = LAB.parent / '.cache'
STAGE = ROOT / 'research_create_rust/.create-lab-build'
PUMPKIN = 'Pumpkin-eda69440e6369c5f8a05c3f69fc809c40dab93a6'
BETA = portable.LAUNCHER / 'target/release-beta2-final'
NAME = 'NextMC-Rust-Create-Preview'
CLIENT_PATCHES = ('horizon-create-placement.patch', 'horizon-create-bearing-motion.patch')

sys.path.insert(0, str(LAB))
from generate_passive_data import generate
from smoke_core import CONFIG


def normalized(content):
    return content.replace(b'\r\n', b'\n')


def patch_tree(tree, patches, live):
    touched = {path for patch in patches for path in re.findall(
        r'^(?:--- a/|\+\+\+ b/)(\S+)', patch.read_text(encoding='utf-8'), re.M)}
    for path in touched:
        file = tree / path
        if file.is_file():
            content = file.read_bytes()
            if b'\r\n' in content:
                file.write_bytes(normalized(content))
    for patch in patches:
        subprocess.run(['git', '-c', 'core.autocrlf=false', 'apply', str(patch)], cwd=tree, check=True)
    for path in touched:
        a, b = tree / path, live / path
        assert a.is_file() == b.is_file(), path
        assert not a.is_file() or normalized(a.read_bytes()) == normalized(b.read_bytes()), path
    return touched


def build(output):
    client = STAGE / 'game-target/fast/horizon-client.exe'
    server = CACHE / 'core-target/debug/pumpkin-harvest-vines-qa.exe'
    portable.require_unbranded_icon_build(client)
    assert pin(server) == pin(CACHE / 'core-target/debug/pumpkin.exe')
    component_source = BETA / 'NextMC-Create-Atlas-Source.zip'
    component_win = BETA / 'NextMC-Create-Atlas-Windows-x64.zip'
    for archive in (component_source, component_win):
        assert pin(archive)['sha256'] == archive.with_suffix('.zip.sha256').read_text().split()[0]

    changes = re.findall(r'for patch in (lab .*?); do', (LAB / 'README.md').read_text(encoding='utf-8'))[-1].split()
    server_patches = [LAB / f'pumpkin-create-{name}.patch' for name in changes]
    assert len(server_patches) == len(list(LAB.glob('pumpkin-create-*.patch'))) == 61
    lab_files = sorted(f for f in LAB.iterdir() if f.suffix in {'.md', '.patch', '.py'})
    deps = set(portable.rust_dependencies(CACHE / PUMPKIN, '-p', 'pumpkin')) | set(portable.rust_dependencies(
        STAGE / 'stage', '-p', 'horizon-client'))
    out_win = output / (NAME + '-Windows-x64.zip')
    out_src = output / (NAME + '-Source.zip')

    with TemporaryDirectory(prefix='nextmc-preview-') as path, ZipFile(component_source) as baseline, ZipFile(component_win) as runtime:
        tmp = Path(path)
        with tarfile.open(CACHE / 'pumpkin-tag.tar.gz') as tar:
            assert all(entry.name.split('/')[0] == PUMPKIN for entry in tar.getmembers())
            tar.extractall(tmp, filter='data')
        pumpkin = tmp / PUMPKIN
        patched = patch_tree(pumpkin, server_patches, CACHE / PUMPKIN)
        assert len(patched) == 77
        assert not (pumpkin / 'assets/datapack/data/minecraft').exists()
        # Replay the client delta on the already published staged source, not on local caches.
        source_files = [n for n in baseline.namelist() if n.startswith('source/') and not n.endswith('/')]
        baseline.extractall(tmp, members=source_files)
        horizon = tmp / 'source'
        patch_tree(horizon, [LAB / name for name in CLIENT_PATCHES], STAGE / 'stage')
        for file in horizon.rglob('*'):
            if file.is_file():
                relative = file.relative_to(horizon)
                assert normalized(file.read_bytes()) == normalized((STAGE / 'stage' / relative).read_bytes()), relative
        datapack = tmp / 'create-passive'
        entries = generate(datapack)
        dependencies = '\n'.join(f'{name} {version}: {license}' for name, version, license in sorted(deps)) + '\n'

        def licenses(z):
            z.write(pumpkin / 'LICENSE', 'licenses/Pumpkin-GPL-3.0.txt')
            z.write(pumpkin / 'assets/NOTICE.md', 'licenses/Pumpkin-assets-NOTICE.md')
            for name in ('LICENSE', 'THIRD_PARTY_NOTICES.md'):
                z.write(horizon / name, f'licenses/Horizon-{name}')
            for name in baseline.namelist():
                if name.startswith('licenses/'):
                    z.writestr(name, baseline.read(name))
            portable.add_rust_licenses(lambda file, name: z.write(file, name) if name.startswith('licenses/') else None, deps)
            z.writestr('licenses/rust-dependencies.txt', dependencies)

        with ZipFile(out_win, 'w', ZIP_DEFLATED, compresslevel=5, strict_timestamps=False) as z:
            for name in ('Start-Server.cmd', 'Play-Create.cmd', 'README.md', 'BUILD.md'):
                z.write(DOCS / name, name)
            z.write(LAB / 'behavior-parity.md', 'lab/behavior-parity.md')
            z.writestr('CreatePreview/player/horizon-mods.txt', 'mod.create:true\nmod.atlas:false\n')
            z.writestr('CreatePreview/server/pumpkin.toml', CONFIG.format(port=25586))
            z.write(client, 'CreatePreview/bin/horizon-client.exe')
            z.write(server, 'CreatePreview/server/pumpkin-create.exe')
            for name in ('dxcompiler.dll', 'DXC-LICENSE-MS.txt', 'DXC-LICENSE-LLVM.txt', 'DXC-NOTICE.txt'):
                z.writestr(f'CreatePreview/bin/{name}', runtime.read(f'target/plain/release/{name}'))
            for file in sorted(datapack.rglob('*')):
                if file.is_file():
                    z.write(file, f'CreatePreview/server/create-lab/datapacks/create-passive/{file.relative_to(datapack).as_posix()}')
            licenses(z)

        with ZipFile(out_src, 'w', ZIP_DEFLATED, compresslevel=5, strict_timestamps=False) as z:
            for name in ('README.md', 'BUILD.md', 'Start-Server.cmd', 'Play-Create.cmd', 'prepare_pumpkin_data.py'):
                z.write(DOCS / name, name)
            z.write(LAB / 'behavior-parity.md', 'lab/behavior-parity.md')
            for file in lab_files:
                z.write(file, 'research_pumpkin_horizon/create-core/' + file.name)
            for tree, prefix in ((horizon, 'research_create_rust/.create-lab-build/stage'),
                                 (pumpkin, 'research_pumpkin_horizon/.cache/' + PUMPKIN)):
                for file in sorted(tree.rglob('*')):
                    if file.is_file():
                        assert not file.is_symlink() and file.suffix.lower() not in {'.jar', '.class', '.dll', '.exe'}, file
                        z.write(file, f'{prefix}/{file.relative_to(tree).as_posix()}')
            licenses(z)
            portable.add_rust_licenses(lambda file, name: z.write(file, name) if name.startswith('source/') else None, deps)

    for archive in (out_win, out_src):
        with ZipFile(archive) as z:
            assert z.testzip() is None and len(set(z.namelist())) == len(z.namelist()), archive
            assert not any(n.lower().endswith(('.jar', '.class', '.dpapi')) for n in z.namelist()), archive
        checksum(archive)
        print(archive, pin(archive), flush=True)
    print(f'PASS: {len(server_patches)} server and {len(CLIENT_PATCHES)} client patches; datapack {entries}', flush=True)


if __name__ == '__main__':
    output = Path(sys.argv[1]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    os.environ['RUSTUP_TOOLCHAIN'] = 'stable'
    build(output)
