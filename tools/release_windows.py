"""Assemble and pin the Windows beta from checked, prebuilt native inputs (see BUILD.md)."""
import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

import package_windows as portable

COMPONENT = 'NextMC-Create-Atlas-Windows-x64.zip'
CLIENT = 'target/plain/release/horizon-client.exe'
PREPARE = 'target/plain/release/horizon-prepare.exe'
LOCK = 'research-lock.json'
DXC = ('dxcompiler.dll', 'DXC-LICENSE-MS.txt', 'DXC-LICENSE-LLVM.txt', 'DXC-NOTICE.txt')
DXC_HASH = '0689e2fee0a1c9df8662a59680469f24e2a3ad7ce6bbbcc9284f7a83172bfc59'


def pin(path):
    with path.open('rb') as file:
        return {'size': path.stat().st_size, 'sha256': hashlib.file_digest(file, 'sha256').hexdigest()}


def checksum(path):
    path.with_name(path.name + '.sha256').write_text(
        f'{pin(path)["sha256"]}  {path.name}\n', encoding='ascii')


def make_component(args):
    source = args.modded_source
    assert (source / '.horizon-revision').read_text().strip() == '9f42064c11efe7ef3e5ed2baad7ddc2a3b36eea0'
    assert 'pub const OUTPUT_VERSION: u32 = 4;' in (source / 'crates/horizon-prepare/src/lib.rs').read_text()
    assert pin(args.dxc / DXC[0])['sha256'] == DXC_HASH
    for binary in (args.client, args.prepare):
        portable.require_unbranded_icon_build(binary)
    java, exporters, classes = portable.exporter_files(source, args.exporters)
    files = {CLIENT: args.client, PREPARE: args.prepare, LOCK: source / LOCK}
    archive = args.output / COMPONENT
    deps = set(portable.rust_dependencies(source, '-p', 'horizon-client', '-p', 'horizon-prepare'))
    with ZipFile(archive, 'w', ZIP_DEFLATED, compresslevel=5, strict_timestamps=False) as z:
        for name, path in files.items():
            z.write(path, name)
        for name in ['manifest.json', *classes]:
            z.write(exporters / name, f'exporters/{name}')
        for path in java:
            z.write(path, path.relative_to(source).as_posix())
        for name in DXC:
            z.write(args.dxc / name, f'target/plain/release/{name}')
        for name in ('LICENSE', 'THIRD_PARTY_NOTICES.md'):
            z.write(source / name, f'licenses/Horizon-{name}')
        z.write(args.create_license, 'licenses/Create-for-Horizon-MIT.txt')
        z.write(args.atlas_license, 'licenses/Horizon-Atlas-MIT.txt')
        portable.add_rust_licenses(z.write, deps)
        z.writestr('licenses/rust-dependencies.txt', '\n'.join(f'{n} {v}: {l}' for n, v, l in sorted(deps)) + '\n')
        z.writestr('SOURCE.txt', 'See NextMC-Create-Atlas-Source.zip in this release.\n')
    checksum(archive)
    values = {key: pin(path) for key, path in zip(('client', 'prepare', 'lock'), files.values())}
    values['archive'] = pin(archive)
    values['dxc'] = pin(args.dxc / DXC[0])
    (args.output / 'create-component.json').write_text(json.dumps(values, separators=(',', ':')), encoding='ascii')
    source_archive = args.output / 'NextMC-Create-Atlas-Source.zip'
    with ZipFile(source_archive, 'w', ZIP_DEFLATED, compresslevel=5, strict_timestamps=False) as z:
        for path in sorted(source.rglob('*')):
            rel = path.relative_to(source)
            if any(part in ('.local', '.git', 'target', '__pycache__') for part in rel.parts):
                continue
            if path.is_symlink() or not path.is_file() or path.suffix.lower() in ('.jar', '.class', '.exe', '.dll'):
                continue
            z.write(path, f'source/{rel.as_posix()}')
        z.write(args.create_license, 'licenses/Create-for-Horizon-MIT.txt')
        z.write(args.atlas_license, 'licenses/Horizon-Atlas-MIT.txt')
        z.write(portable.LAUNCHER / 'BUILD.md', 'BUILD.md')
    checksum(source_archive)


def make_release(args):
    config = args.output / 'create-component.json'
    if pin(args.output / COMPONENT) != json.loads(config.read_bytes())['archive']:
        raise ValueError('Component ZIP does not match create-component.json')
    env = os.environ | {'NEXT_MC_CREATE_COMPONENT': config.read_text(encoding='ascii')}
    env.pop('NEXT_MC_LAUNCHER_ICON_RES', None)
    subprocess.run(['npm.cmd', '--prefix', 'ui', 'run', 'build'], cwd=portable.LAUNCHER, check=True)
    subprocess.run(['cargo', 'build', '--release', '--locked', '--features', 'gui', '--bin', 'next-mc-launcher'],
                   cwd=portable.LAUNCHER, env=env, check=True)
    archive = args.output / 'NextMC-Windows-x64.zip'
    portable.package(archive, dxc=args.dxc, component_config=config)
    with TemporaryDirectory(prefix='nextmc-setup-') as payload:
        with ZipFile(archive) as z:
            z.extractall(payload)
        subprocess.run([str(args.iscc), f'/DPayload={payload}', f'/DOutput={args.output}',
                        str(portable.LAUNCHER / 'tools/nextmc.iss')], check=True)
    checksum(args.output / 'NextMC-Setup-Windows-x64.exe')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('step', choices=('component', 'release'))
    parser.add_argument('output', type=Path)
    parser.add_argument('--dxc', type=Path, required=True)
    for name in ('modded-source', 'client', 'prepare', 'exporters', 'create-license', 'atlas-license', 'iscc'):
        parser.add_argument(f'--{name}', type=Path)
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.step == 'component':
        make_component(args)
    else:
        make_release(args)
