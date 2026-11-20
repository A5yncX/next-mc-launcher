use std::fs::{self, File};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::time::Duration;

use super::{install, report, Report};
use crate::layout::Layout;
use serde::Deserialize;

use serde_json::Value;
use sha2::{Digest, Sha256};

const COMPONENT: &str = "create-atlas-beta.1";
const ASSET: &str = "NextMC-Create-Atlas-Windows-x64.zip";
const RELEASE: &str = "https://github.com/A5yncX/next-mc-launcher/releases/download/v0.1.0-beta.1/";
const CLIENT: &str = "target/plain/release/horizon-client.exe";
const PREPARE: &str = "target/plain/release/horizon-prepare.exe";
const DXC: &str = "target/plain/release/dxcompiler.dll";

#[derive(Deserialize)]
struct Pin {
    size: u64,
    sha256: String,
}

#[derive(Deserialize)]
struct Pins {
    archive: Pin,
    client: Pin,
    prepare: Pin,
    lock: Pin,
    dxc: Pin,
}

fn pins() -> Result<Pins, &'static str> {
    serde_json::from_str(option_env!("NEXT_MC_CREATE_COMPONENT").unwrap_or(""))
        .map_err(|_| "此开发构建没有固定机械动力组件；请使用 Next MC 正式打包的发行版。")
}
const MOD_SETTINGS: &str = "horizon-mods.txt";
const ATLAS: &str = "mod.atlas";
const JAR: &str = "create-1.21.1-6.0.10.jar";
const JAR_HASH: &str = "ef87fe5709f1ba1f5b8bb20a2925b5afb4669e178fd6d8bf10c167759eefe37a";
const IMPORT: &str = "horizon-mods/create-resources";
pub(super) const OFFLINE_ONLY: &str =
    "开启机械动力时，请使用离线启动。关闭开关后可继续用正版账号启动普通客户端。";

pub(super) fn directory(data: &Path, id: u32) -> PathBuf {
    data.join("create-instances").join(id.to_string())
}

pub(super) fn enabled(data: &Path, id: u32) -> bool {
    directory(data, id).join("enabled").is_file()
}

pub(super) fn set_enabled(data: &Path, id: u32, value: bool) -> io::Result<()> {
    let dir = directory(data, id);
    let flag = dir.join("enabled");
    if value {
        fs::create_dir_all(dir)?;
        fs::write(flag, [])
    } else {
        match fs::remove_file(flag) {
            Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(()),
            other => other,
        }
    }
}

pub(super) fn atlas_enabled(data: &Path, id: u32) -> bool {
    fs::read_to_string(directory(data, id).join(MOD_SETTINGS))
        .is_ok_and(|settings| atlas_is_on(&settings))
}

pub(super) fn set_atlas(data: &Path, id: u32, enabled: bool) -> io::Result<()> {
    update_settings(&directory(data, id).join(MOD_SETTINGS), |settings| {
        set_mod(settings, ATLAS, enabled)
    })
}

fn component(data: &Path) -> PathBuf {
    data.join("components").join(COMPONENT)
}

pub(super) fn available(data: &Path) -> Result<(), &'static str> {
    pins()?;
    let root = component(data);
    if [CLIENT, PREPARE, DXC, "research-lock.json"]
        .iter()
        .all(|file| root.join(file).is_file())
    {
        Ok(())
    } else {
        Err("尚未安装 Create + Atlas 预编译组件。")
    }
}

pub(super) fn can_install() -> bool {
    pins().is_ok()
}

pub(super) fn variant(base: &Layout) -> Result<Layout, String> {
    let root = component(&base.data);
    let pins = pins()?;
    check(&root, &pins).map_err(|e| format!("机械动力组件校验失败，请重新安装：{e}"))?;
    Ok(base.create_variant(root))
}

fn check(root: &Path, pins: &Pins) -> io::Result<()> {
    for (name, pin) in [
        (CLIENT, &pins.client),
        (PREPARE, &pins.prepare),
        (DXC, &pins.dxc),
        ("research-lock.json", &pins.lock),
    ] {
        verify(&root.join(name), pin.size, &pin.sha256)?;
    }
    Ok(())
}

pub(super) fn resources_ready(data: &Path) -> bool {
    let dir = data.join("resources-create-v4");
    let manifest = |name| -> Option<Value> {
        serde_json::from_reader(File::open(dir.join(name)).ok()?.take(8192)).ok()
    };
    manifest("horizon-prepare.json").is_some_and(|v| v["output_version"] == 4)
        && manifest("horizon-resources.json")
            .is_some_and(|v| v["schema"] == 7 && v["minecraft"] == "26.3")
}

pub(super) fn prepare_instance(dir: &Path) -> io::Result<()> {
    let import = dir.join(IMPORT);
    fs::create_dir_all(&import)?;
    let jar = import.join(JAR);
    if jar.exists() {
        verify(&jar, 19_123_767, JAR_HASH)?;
    }
    prepare_mods(&dir.join(MOD_SETTINGS))
}

pub(super) fn install_component(data: &Path, emit: &dyn Fn(Report)) -> Result<String, String> {
    let pins = pins()?;
    let target = component(data);
    if check(&target, &pins).is_ok() {
        return Ok("Create + Atlas 组件已安装。".into());
    }
    let stage = target.with_extension("installing");
    let backup = target.with_extension("previous");
    fs::create_dir_all(target.parent().unwrap()).map_err(|e| e.to_string())?;
    if backup.exists() && !target.exists() {
        fs::rename(&backup, &target).map_err(|e| e.to_string())?;
    }
    if stage.exists() {
        fs::remove_dir_all(&stage).map_err(|e| e.to_string())?;
    }
    let extracted = stage.join("component");
    fs::create_dir_all(&extracted).map_err(|e| e.to_string())?;
    let result = (|| -> Result<(), String> {
        let local_zip = std::env::current_exe()
            .map_err(|e| e.to_string())?
            .with_file_name(ASSET);
        let downloaded = stage.join(ASSET);
        let archive = if local_zip.is_file() {
            let mut file = File::create_new(&downloaded).map_err(|e| e.to_string())?;
            io::copy(
                &mut File::open(local_zip)
                    .map_err(|e| e.to_string())?
                    .take(pins.archive.size + 1),
                &mut file,
            )
            .map_err(|e| e.to_string())?;
            downloaded
        } else {
            emit(report(
                "download",
                "从 GitHub 下载 Create + Atlas 预编译组件…",
            ));
            let response = ureq::AgentBuilder::new()
                .timeout(Duration::from_secs(600))
                .build()
                .get(&format!("{RELEASE}{ASSET}"))
                .call()
                .map_err(|e| format!("下载组件失败：{e}"))?;
            let mut file = File::create_new(&downloaded).map_err(|e| e.to_string())?;
            io::copy(
                &mut response.into_reader().take(pins.archive.size + 1),
                &mut file,
            )
            .map_err(|e| e.to_string())?;
            downloaded
        };
        emit(report("verify", "校验并解压 Create + Atlas 组件…"));
        verify(&archive, pins.archive.size, &pins.archive.sha256)
            .map_err(|e| format!("组件 ZIP 校验失败：{e}"))?;
        let tar = PathBuf::from(std::env::var_os("SystemRoot").ok_or("找不到系统解压工具。")?)
            .join("System32/tar.exe");
        let status = install::quiet(std::process::Command::new(tar))
            .arg("-xf")
            .arg(&archive)
            .arg("-C")
            .arg(&extracted)
            .status()
            .map_err(|e| e.to_string())?;
        if !status.success() {
            return Err("组件 ZIP 解压失败。".into());
        }
        check(&extracted, &pins).map_err(|e| format!("解压后的组件校验失败：{e}"))?;
        if backup.exists() {
            fs::remove_dir_all(&backup).map_err(|e| e.to_string())?;
        }
        if target.exists() {
            fs::rename(&target, &backup).map_err(|e| e.to_string())?;
        }
        if let Err(error) = fs::rename(&extracted, &target) {
            if backup.exists() {
                let _ = fs::rename(&backup, &target);
            }
            return Err(error.to_string());
        }
        Ok(())
    })();
    let _ = fs::remove_dir_all(stage);
    result?;
    let _ = fs::remove_dir_all(backup);
    Ok("Create + Atlas 预编译组件已安装，可按实例启用。".into())
}

fn atlas_is_on(settings: &str) -> bool {
    let values = || {
        settings.lines().filter_map(|line| {
            let (name, value) = line.split_once(':')?;
            (name.trim() == ATLAS).then(|| value.trim())
        })
    };
    values().any(|value| value == "true") && !values().any(|value| value == "false")
}

fn set_mod(settings: &str, key: &str, enabled: bool) -> String {
    let mut out = format!("{key}:{enabled}\n");
    for line in settings.lines() {
        if !line
            .split_once(':')
            .is_some_and(|(name, _)| name.trim() == key)
        {
            out.push_str(line);
            out.push('\n');
        }
    }
    out
}

fn prepare_mods(path: &Path) -> io::Result<()> {
    update_settings(path, |settings| {
        set_mod(
            &set_mod(settings, ATLAS, atlas_is_on(settings)),
            "mod.create",
            true,
        )
    })
}

fn update_settings(path: &Path, change: impl FnOnce(&str) -> String) -> io::Result<()> {
    let existing = match fs::read_to_string(path) {
        Ok(text) => text,
        Err(e) if e.kind() == io::ErrorKind::NotFound => String::new(),
        Err(e) => return Err(e),
    };
    let settings = change(&existing);
    if settings == existing {
        return Ok(());
    }
    let temporary = path.with_extension(format!("{}.tmp", std::process::id()));
    let mut file = File::create_new(&temporary)?;
    let written = file.write_all(settings.as_bytes());
    drop(file);
    let result = written.and_then(|()| fs::rename(&temporary, path));
    if result.is_err() {
        let _ = fs::remove_file(temporary);
    }
    result
}

fn verify(path: &Path, size: u64, expected: &str) -> io::Result<()> {
    let metadata = fs::symlink_metadata(path)?;
    if metadata.is_file() && metadata.len() == size {
        let mut hash = Sha256::new();
        let count = io::copy(&mut File::open(path)?.take(size + 1), &mut hash)?;
        if count == size && format!("{:x}", hash.finalize()) == expected {
            return Ok(());
        }
    }
    Err(io::Error::new(
        io::ErrorKind::InvalidData,
        "文件大小或 SHA-256 不匹配",
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn create_is_opt_in_and_disabling_preserves_both_saves() {
        let root = std::env::temp_dir().join(format!("nextmc-create-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        let vanilla = root.join("offline-instance");
        fs::create_dir_all(&vanilla).unwrap();
        fs::write(vanilla.join("world"), "abc").unwrap();
        assert!(!enabled(&root, 0));
        assert!(available(&root).is_err());
        assert!(!resources_ready(&root));
        set_enabled(&root, 0, true).unwrap();
        assert!(enabled(&root, 0));
        assert!(!enabled(&root, 1));
        let world = directory(&root, 0).join("world");
        fs::write(&world, "create").unwrap();
        let mods = world.with_file_name("horizon-mods.txt");
        fs::write(
            &mods,
            "mod.create:false\nkey.create.wrench:key.keyboard.x\n",
        )
        .unwrap();
        assert!(!atlas_enabled(&root, 0));
        prepare_instance(world.parent().unwrap()).unwrap();
        assert_eq!(
            fs::read_to_string(&mods).unwrap(),
            "mod.create:true\nmod.atlas:false\nkey.create.wrench:key.keyboard.x\n"
        );
        set_atlas(&root, 0, true).unwrap();
        assert!(atlas_enabled(&root, 0));
        assert!(!atlas_enabled(&root, 1));
        prepare_mods(&mods).unwrap();
        assert!(atlas_enabled(&root, 0));
        assert!(fs::read_to_string(&mods)
            .unwrap()
            .contains("key.create.wrench:key.keyboard.x"));
        set_atlas(&root, 0, false).unwrap();
        assert!(!atlas_enabled(&root, 0));
        assert!(fs::read_to_string(&mods)
            .unwrap()
            .contains("mod.create:true"));
        verify(
            &vanilla.join("world"),
            3,
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        )
        .unwrap();
        assert!(verify(&world, 6, JAR_HASH).is_err());
        set_enabled(&root, 0, false).unwrap();
        assert!(!enabled(&root, 0));
        assert_eq!(fs::read_to_string(world).unwrap(), "create");
        assert_eq!(fs::read_to_string(vanilla.join("world")).unwrap(), "abc");
        fs::remove_dir_all(root).unwrap();
    }
}
