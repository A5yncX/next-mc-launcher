use crate::layout::Layout;
use std::env;
use std::fs::{self, File};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};

use serde::Deserialize;
use sha1::{Digest, Sha1};

use super::{report, Report, CANCELLED};

const VERSION: &str = "26.3";
const MANIFEST: &str = "11f1aefe473eefba0af62e3286c33b692807b2eb";
const MANIFEST_PATH: &str = "versions/26.3/26.3.json";
const SERVER_PATH: &str = "server-jars/26.3.jar";

#[derive(Deserialize)]
struct Artifact {
    url: String,
    sha1: String,
    size: u64,
    #[serde(default)]
    path: String,
}

#[derive(Deserialize)]
struct DownloadItems {
    client: Artifact,
    server: Artifact,
}

#[derive(Deserialize)]
struct IndexInfo {
    id: String,
    #[serde(flatten)]
    artifact: Artifact,
}

#[derive(Deserialize)]
struct Version {
    id: String,
    downloads: DownloadItems,
    libraries: Vec<Library>,
    #[serde(rename = "assetIndex")]
    index: IndexInfo,
}

#[derive(Deserialize)]
struct Library {
    name: String,
    downloads: LibraryDownload,
    #[serde(default)]
    rules: Vec<Rule>,
}

#[derive(Deserialize)]
struct LibraryDownload {
    artifact: Artifact,
}

#[derive(Deserialize)]
struct Rule {
    action: String,
    os: Option<Os>,
}

#[derive(Deserialize)]
struct Os {
    name: String,
}

#[derive(Deserialize)]
struct AssetIndex {
    objects: std::collections::BTreeMap<String, Asset>,
}

#[derive(Deserialize)]
struct Asset {
    hash: String,
    size: u64,
}

struct Item {
    relative: PathBuf,
    metadata: Artifact,
}

fn hash_ok(value: &str) -> bool {
    value.len() == 40
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || matches!(b, b'a'..=b'f'))
}

fn relative(value: &str) -> Result<PathBuf, String> {
    if value.split('/').all(|part| {
        !part.is_empty()
            && !part.starts_with('.')
            && !part.ends_with('.')
            && part
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b"._-+".contains(&b))
    }) {
        Ok(value.into())
    } else {
        Err(format!("不可用的资源路径：{value}"))
    }
}

fn official_url(url: &str) -> bool {
    [
        "piston-meta.mojang.com",
        "piston-data.mojang.com",
        "libraries.minecraft.net",
        "resources.download.minecraft.net",
    ]
    .iter()
    .any(|host| {
        url.strip_prefix("https://")
            .and_then(|u| u.split_once('/'))
            .is_some_and(|(h, _)| h == *host)
    })
}

fn cancel(flag: &AtomicBool) -> Result<(), String> {
    if flag.load(Ordering::Relaxed) {
        Err(CANCELLED.into())
    } else {
        Ok(())
    }
}

fn verified(path: &Path, item: &Item, flag: &AtomicBool) -> Result<bool, String> {
    cancel(flag)?;
    let Ok(file) = File::open(path) else {
        return Ok(false);
    };
    let size = item.metadata.size;
    if size != 0
        && !file
            .metadata()
            .is_ok_and(|meta| meta.is_file() && meta.len() == size)
    {
        return Ok(false);
    }
    let limit = if size == 0 { 1_000_000 } else { size };
    let mut hash = Sha1::new();
    let mut reader = file.take(limit + 1);
    let mut buf = [0; 65536];
    loop {
        cancel(flag)?;
        let Ok(n) = reader.read(&mut buf) else {
            return Ok(false);
        };
        if n == 0 {
            break;
        }
        hash.update(&buf[..n]);
    }
    Ok(format!("{:x}", hash.finalize()) == item.metadata.sha1)
}

fn materialize(
    item: &Item,
    target: &Path,
    source: Option<&Path>,
    agent: &ureq::Agent,
    flag: &AtomicBool,
    progress: &mut dyn FnMut(u64),
) -> Result<(), String> {
    let meta = &item.metadata;
    if !hash_ok(&meta.sha1) || !official_url(&meta.url) || meta.size > 250_000_000 {
        return Err("资源清单包含不支持的来源、校验值或大小。".into());
    }
    cancel(flag)?;
    let mut input: Box<dyn Read> = match source {
        Some(path) => Box::new(File::open(path).map_err(|e| format!("{}：{e}", path.display()))?),
        None => Box::new(
            agent
                .get(&meta.url)
                .call()
                .map_err(|e| format!("下载 {} 失败：{e}", item.relative.display()))?
                .into_reader(),
        ),
    };
    let parent = target.parent().ok_or("缺少目标目录。")?;
    fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    let part = target.with_extension("nextmc-part");
    let result = (|| {
        let mut out = File::create(&part).map_err(|e| e.to_string())?;
        let mut hash = Sha1::new();
        let mut buf = [0; 65536];
        let mut written = 0u64;
        let limit = if meta.size == 0 { 1_000_000 } else { meta.size };
        loop {
            cancel(flag)?;
            let n = input.read(&mut buf).map_err(|e| e.to_string())?;
            if n == 0 {
                break;
            }
            written += n as u64;
            if written > limit {
                return Err("资源响应大于清单中的大小。".into());
            }
            out.write_all(&buf[..n]).map_err(|e| e.to_string())?;
            hash.update(&buf[..n]);
            if source.is_none() {
                progress(written);
            }
        }
        cancel(flag)?;
        if (meta.size != 0 && written != meta.size) || format!("{:x}", hash.finalize()) != meta.sha1
        {
            return Err(format!("校验未通过：{}", item.relative.display()));
        }
        out.sync_all().map_err(|e| e.to_string())?;
        drop(out);
        fs::rename(&part, target).map_err(|e| format!("{}：{e}", target.display()))
    })();
    if result.is_err() {
        let _ = fs::remove_file(&part);
    }
    result
}

fn local_source(
    item: &Item,
    sources: &[PathBuf],
    flag: &AtomicBool,
) -> Result<Option<PathBuf>, String> {
    for source in sources {
        let path = source.join(&item.relative);
        if verified(&path, item, flag)? {
            return Ok(Some(path));
        }
        if item.relative == Path::new(SERVER_PATH) {
            if let Some(parent) = source.parent() {
                let path = parent.join(SERVER_PATH);
                if verified(&path, item, flag)? {
                    return Ok(Some(path));
                }
            }
        }
    }
    Ok(None)
}

fn ensure_metadata(
    item: &Item,
    cache: &Path,
    sources: &[PathBuf],
    agent: &ureq::Agent,
    flag: &AtomicBool,
    download: bool,
    emit: &dyn Fn(Report),
) -> Result<PathBuf, String> {
    let target = cache.join(&item.relative);
    if !verified(&target, item, flag)? {
        let source = local_source(item, sources, flag)?;
        if source.is_none() && !download {
            return Err(missing(item));
        }
        if source.is_none() {
            emit(report("download", "下载并校验 Mojang 官方资源清单…"));
        }
        materialize(item, &target, source.as_deref(), agent, flag, &mut |_| {})?;
    }
    Ok(target)
}

fn missing(item: &Item) -> String {
    format!(
        "本机缺少可校验的 {}。请选择正确的 26.3 安装目录，或点击「下载缺失文件」。",
        item.relative.display()
    )
}

fn parse<T: serde::de::DeserializeOwned>(path: PathBuf) -> Result<T, String> {
    serde_json::from_reader(io::BufReader::new(
        File::open(path).map_err(|e| e.to_string())?,
    ))
    .map_err(|e| format!("无法解析版本清单：{e}"))
}

fn library_items(libraries: Vec<Library>) -> Result<Vec<Item>, String> {
    libraries
        .into_iter()
        .filter(|library| {
            let allowed = library
                .rules
                .iter()
                .rev()
                .find(|rule| rule.os.as_ref().is_none_or(|os| os.name == "windows"))
                .map_or(library.rules.is_empty(), |rule| rule.action == "allow");
            let classifier = library.name.split(':').nth(3).unwrap_or("");
            // shortcut: the pinned 26.3 metadata only uses OS-name rules; revisit when changing versions/platforms.
            allowed
                && !["arm64", "aarch64", "aarch_64"]
                    .iter()
                    .any(|suffix| classifier.ends_with(suffix))
        })
        .map(|library| {
            let metadata = library.downloads.artifact;
            let path = relative(&metadata.path)?;
            Ok(Item {
                relative: Path::new("libraries").join(path),
                metadata,
            })
        })
        .collect()
}

pub(super) fn collect(
    layout: &Layout,
    preferred: Option<&Path>,
    download: bool,
    flag: &AtomicBool,
    emit: &dyn Fn(Report),
) -> Result<(PathBuf, Option<PathBuf>), String> {
    let lock: serde_json::Value = parse(layout.root.join("research-lock.json"))?;
    if lock["minecraft"]["version"] != VERSION || lock["minecraft"]["manifest_sha1"] != MANIFEST {
        return Err("当前图形启动器只准备与本机 Horizon 构建匹配的 26.3 资源。".into());
    }
    let app = env::var_os("APPDATA").map(PathBuf::from);
    let mut sources = Vec::new();
    if let Some(preferred) = preferred {
        if !matches!(preferred.components().next(), Some(std::path::Component::Prefix(p)) if matches!(p.kind(), std::path::Prefix::Disk(_)))
            || !preferred.is_absolute()
            || !preferred.is_dir()
        {
            return Err(
                "请输入本机 Minecraft 安装目录的绝对路径，例如 D:\\Games\\.minecraft。".into(),
            );
        }
        sources.push(preferred.to_path_buf());
    }
    if let Some(app) = &app {
        sources.extend([
            app.join(".minecraft"),
            app.join("horizon-launcher/minecraft"),
        ]);
    }
    let java = sources
        .iter()
        .map(|dir| dir.join("runtime/java-runtime-epsilon/windows-x64/java-runtime-epsilon"))
        .find(|p| p.join("bin/javac.exe").is_file());
    let cache = layout.data.join("minecraft");
    let agent = ureq::AgentBuilder::new()
        .redirects(0)
        .timeout_connect(Duration::from_secs(5))
        .timeout_read(Duration::from_secs(5))
        .timeout(Duration::from_secs(120))
        .build();
    emit(report("verify", "检查本机 Minecraft 26.3 资源清单…"));
    let manifest = Item {
        relative: MANIFEST_PATH.into(),
        metadata: Artifact {
            url: format!("https://piston-meta.mojang.com/v1/packages/{MANIFEST}/{VERSION}.json"),
            sha1: MANIFEST.into(),
            size: 0,
            path: String::new(),
        },
    };
    let version: Version = parse(ensure_metadata(
        &manifest, &cache, &sources, &agent, flag, download, emit,
    )?)?;
    if version.id != VERSION
        || version.downloads.client.sha1 != lock["minecraft"]["client_sha1"]
        || version.downloads.server.sha1 != lock["minecraft"]["server_sha1"]
    {
        return Err("26.3 清单与当前 Horizon 的客户端或服务端校验值不符。".into());
    }
    let index = Item {
        relative: Path::new("assets/indexes")
            .join(relative(&format!("{}.json", version.index.id))?),
        metadata: version.index.artifact,
    };
    let assets: AssetIndex = parse(ensure_metadata(
        &index, &cache, &sources, &agent, flag, download, emit,
    )?)?;
    let mut items = vec![
        Item {
            relative: "versions/26.3/26.3.jar".into(),
            metadata: version.downloads.client,
        },
        Item {
            relative: SERVER_PATH.into(),
            metadata: version.downloads.server,
        },
    ];
    items.extend(library_items(version.libraries)?);
    for Asset { hash, size } in assets.objects.into_values() {
        if !hash_ok(&hash) {
            return Err("资产索引包含无效校验值。".into());
        }
        let prefix = &hash[..2];
        items.push(Item {
            relative: format!("assets/objects/{prefix}/{hash}").into(),
            metadata: Artifact {
                url: format!("https://resources.download.minecraft.net/{prefix}/{hash}"),
                sha1: hash,
                size,
                path: String::new(),
            },
        });
    }
    let total = items.len();
    let mut last = Instant::now();
    let mut queue = Vec::new();
    for (i, item) in items.into_iter().enumerate() {
        let target = cache.join(&item.relative);
        if !verified(&target, &item, flag)? {
            if let Some(source) = local_source(&item, &sources, flag)? {
                materialize(&item, &target, Some(&source), &agent, flag, &mut |_| {})?;
            } else if download {
                queue.push(item);
            } else {
                return Err(missing(&item));
            }
        }
        if last.elapsed() >= Duration::from_millis(100) || i + 1 == total {
            last = Instant::now();
            let mut p = report("verify", "校验并复用本机已有文件…");
            p.files = Some([i + 1, total]);
            p.fraction = Some((i + 1) as f64 / total as f64);
            emit(p);
        }
    }
    let total = queue.len();
    let bytes: u64 = queue.iter().map(|item| item.metadata.size).sum();
    let mut done = 0;
    for (i, item) in queue.into_iter().enumerate() {
        let name = item.relative.file_name().unwrap().to_string_lossy();
        let update = |current, count| {
            let mut p = report("download", format!("下载并校验：{name}"));
            p.files = Some([count, total]);
            p.bytes = Some([done + current, bytes]);
            p.fraction = Some((done + current) as f64 / bytes.max(1) as f64);
            emit(p);
        };
        // Avoid queueing thousands of UI events during small asset downloads.
        if i == 0 {
            update(0, 0);
        }
        let mut update_bytes = |current| {
            if last.elapsed() >= Duration::from_millis(100) {
                last = Instant::now();
                update(current, i);
            }
        };
        materialize(
            &item,
            &cache.join(&item.relative),
            None,
            &agent,
            flag,
            &mut update_bytes,
        )?;
        if i + 1 == total {
            update(item.metadata.size, i + 1);
        }
        done += item.metadata.size;
    }
    cancel(flag)?;
    Ok((cache, java))
}

pub(super) fn server_jar(cache: &Path) -> PathBuf {
    cache.join(SERVER_PATH)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_mojang_https_and_relative_paths_are_accepted() {
        assert!(official_url(
            "https://piston-data.mojang.com/v1/objects/file"
        ));
        for url in [
            "http://piston-data.mojang.com/a",
            "https://piston-data.mojang.com.evil/a",
            "https://piston-data.mojang.com@evil/a",
        ] {
            assert!(!official_url(url));
        }
        assert!(relative("org/lwjgl/lwjgl-3.4+2.jar").is_ok());
        for path in ["../file", "C:/file", "/file", "a\\b", "a//b", "a/.. /file"] {
            assert!(relative(path).is_err());
        }
    }
}
