"""Assemble the Windows x64 portable ZIP after building both local projects."""
import hashlib
import json
import mmap
import os
from pathlib import Path
import re
import subprocess
import sys
from zipfile import ZIP_DEFLATED, ZipFile

LAUNCHER = Path(__file__).resolve().parents[1]
HORIZON = LAUNCHER.with_name("horizon")
RUST_TARGET = "x86_64-pc-windows-msvc"
PARITY = "mods/horizon/src/test/java/dev/horizonlab/parity"


def command(root, *args):
    return subprocess.check_output(args, cwd=root).decode("utf-8")


def exporter_files(root=HORIZON, bundle=None):
    compiler = root / "crates/horizon-prepare/src/exporters.rs"
    digest = hashlib.sha256(b"exporters-v1 --release -proc:none -encoding UTF-8")
    digest.update(compiler.read_bytes().replace(b"\r", b""))
    # Match Rust Path ordering, not Windows pathlib's case-folded ordering.
    java = sorted((root / PARITY).rglob("*.java"), key=lambda p: p.parts)
    if not java:
        raise ValueError("Horizon exporter sources not found")
    for path in [*java, root / "research-lock.json"]:
        content = path.read_bytes().replace(b"\r", b"")
        digest.update(f"{path.relative_to(root).as_posix()}\0{len(content)}\0".encode())
        digest.update(content)
    key = digest.hexdigest()
    bundle = bundle or root / ".local/exporters" / key
    manifest = json.loads((bundle / "manifest.json").read_bytes())
    classes = manifest["classes"]
    if manifest["key"] != key or not classes:
        raise ValueError("Exporter bundle does not match this Horizon source")
    for name, checksum in classes.items():
        p = Path(name)
        if not re.fullmatch(r"(?:client|server)/dev/horizonlab/parity/[\w/$.-]+\.class", name) or ".." in p.parts:
            raise ValueError(f"Unexpected exporter path: {name}")
        if hashlib.sha256((bundle / p).read_bytes()).hexdigest() != checksum:
            raise ValueError(f"Unexpected exporter checksum: {name}")
    return java, bundle, classes


def rust_dependencies(root, *features):
    tree = command(root, "cargo", "tree", "--locked", "--offline", "--target", RUST_TARGET,
                   "--edges", "normal,build", "--prefix", "none", "--format", "{p}|{l}", *features)
    for line in tree.splitlines():
        if match := re.fullmatch(r"([\w-]+) v([\w.+-]+)\|(.+?)(?: \(\*\))?", line):
            yield match[1], match[2], match[3]


def add_rust_licenses(add, deps):
    cargo_home = Path(os.environ.get('CARGO_HOME', Path.home() / '.cargo'))
    registries = sorted(cargo_home.glob('registry/src/index.crates.io-*'))
    for name, version, license in sorted(deps):
        crate = f'{name}-{version}'
        path = next((registry / crate for registry in registries if (registry / crate).is_dir()), None)
        if not path:
            raise ValueError(f'Missing Cargo registry source: {crate}')
        for notice in sorted(path.iterdir()):
            if notice.is_file() and notice.name.upper().startswith(('LICENSE', 'LICENCE', 'COPYING', 'NOTICE', 'COPYRIGHT')):
                add(notice, f'licenses/rust/{crate}/{notice.name}')
        if 'MPL-2.0' in license:
            for file in sorted(path.rglob('*')):
                if file.is_file() and file.name not in ('.cargo-ok', '.cargo_vcs_info.json'):
                    add(file, f'source/third-party/{crate}/{file.relative_to(path).as_posix()}')


def require_unbranded_icon_build(path):
    # The local .res always contains the official Java 26.3 32px PNG.
    prefix = bytes.fromhex('89504e470d0a1a0a0000000d494844520000002000000020')
    with path.open('rb') as exe, mmap.mmap(exe.fileno(), 0, access=mmap.ACCESS_READ) as contents:
        pos = contents.find(prefix)
        while pos != -1:
            if hashlib.sha1(contents[pos:pos + 2063]).hexdigest() == 'af96f55a90eaf11b327f1b5f8834a051027dc506':
                raise ValueError(f'Rebuild without the local Minecraft icon before packaging: {path}')
            pos = contents.find(prefix, pos + len(prefix))


def package(output, dxc=None, component_config=None):
    require_unbranded_icon_build(LAUNCHER / 'target/release/next-mc-launcher.exe')
    require_unbranded_icon_build(HORIZON / 'target/plain/release/horizon-client.exe')
    subprocess.run([sys.executable, "tools/check_public_tree.py"], cwd=HORIZON, check=True)
    java, exporters, classes = exporter_files()
    horizon_paths = command(HORIZON, "git", "-c", "core.quotePath=false", "ls-files", "-z").split("\0")
    deps = set(rust_dependencies(LAUNCHER, "--features", "gui")) | set(rust_dependencies(
        HORIZON, "-p", "horizon-game", "-p", "horizon-prepare", "--no-default-features",
        "--features", "horizon-game/audio,horizon-game/controllers"))
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(".zip.tmp")
    try:
        with ZipFile(partial, "w", ZIP_DEFLATED, compresslevel=5, strict_timestamps=False) as zip:
            def add(file, name):
                zip.write(file, f"NextMC/{name}")

            def text(name, content):
                zip.writestr(f"NextMC/{name}", content)

            for name in ("next-mc-launcher.exe", "mc-login.exe"):
                add(LAUNCHER / "target/release" / name, name)
            for name in ("horizon-client.exe", "horizon-prepare.exe"):
                add(HORIZON / "target/plain/release" / name, f"horizon/target/plain/release/{name}")
            if dxc is not None:
                for name in ('dxcompiler.dll', 'DXC-LICENSE-MS.txt', 'DXC-LICENSE-LLVM.txt', 'DXC-NOTICE.txt'):
                    add(dxc / name, f'horizon/target/plain/release/{name}')
            for name in ("research-lock.json", "LICENSE", "THIRD_PARTY_NOTICES.md",
                         "LICENSES/GPL-3.0.txt", "LICENSES/MIT.txt"):
                add(HORIZON / name, f"horizon/{name}")
            for path in java:
                add(path, f"horizon/{path.relative_to(HORIZON).as_posix()}")
            for name in ["manifest.json", *classes]:
                add(exporters / name, f"horizon/exporters/{name}")
            for name in ("INSTALL.zh-CN.md", "BUILD.md", "LICENSE"):
                add(LAUNCHER / name, name)
            if component_config:
                add(component_config, 'create-component.json')
            for name in sorted(set(horizon_paths) - {"", "CLAUDE.md"}):
                path = HORIZON / name
                if path.is_symlink():
                    raise ValueError(f"Unexpected source symlink: {name}")
                add(path, f"source/horizon/{name}")
            source = [".gitignore", "Cargo.toml", "Cargo.lock", "README.md", "LICENSE", "BUILD.md", "INSTALL.zh-CN.md",
                      "ui/index.html", "ui/src.jsx", "ui/app.css", "ui/vite.config.js", "ui/package.json", "ui/package-lock.json",
                      "tools/package_windows.py", "tools/local_minecraft_icon.py", "tools/release_windows.py",
                      "tools/nextmc.iss", "tools/horizon-local.patch"]
            source += [p.relative_to(LAUNCHER).as_posix() for d in ("src", "tests", "licenses")
                       for p in (LAUNCHER / d).rglob("*") if p.suffix in (".rs", ".txt") and p.is_file()]
            for name in sorted(source):
                add(LAUNCHER / name, f"source/mc-login/{name}")
            for path in sorted((LAUNCHER / "licenses").glob("*.txt")):
                add(path, f"licenses/{path.name}")
            add_rust_licenses(add, deps)
            text("licenses/rust-dependencies.txt", "\n".join(f"{n} {v}: {l}" for n, v, l in sorted(deps)) + "\n")
            js = LAUNCHER / "ui"
            npm = json.loads((js / "package-lock.json").read_bytes())["packages"]
            for name, metadata in sorted(npm.items()):
                if not name.startswith("node_modules/") or metadata.get("dev"):
                    continue
                for notice in sorted((js / name).glob("LICENSE*")):
                    if notice.is_file():
                        add(notice, f"licenses/ui/{name.removeprefix('node_modules/')}/{notice.name}")
            text("BUILD-INFO.txt", "Horizon upstream revision: " + command(HORIZON, "git", "rev-parse", "HEAD")
                 + "Local Horizon changes are included in source/horizon.\n"
                 + command(LAUNCHER, "rustc", "-Vv"))
        partial.replace(output)
    finally:
        partial.unlink(missing_ok=True)
    with output.open('rb') as file:
        checksum = hashlib.file_digest(file, 'sha256').hexdigest()
    output.with_suffix('.zip.sha256').write_text(f'{checksum}  {output.name}\n', encoding='ascii')
    print(f"{output} ({output.stat().st_size / 2**20:.1f} MiB)")


if __name__ == "__main__":
    package(Path(sys.argv[1]).absolute() if len(sys.argv) > 1 else LAUNCHER / "target/NextMC-Windows-x64.zip")
