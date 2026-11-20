use crate::layout::Layout;
use serde::Serialize;
use std::fs;
use std::io::ErrorKind;
use std::path::{Path, PathBuf};

#[derive(Serialize)]
pub(super) struct Instance {
    pub id: u32,
    pub name: String,
}

impl Instance {
    pub fn path(&self, layout: &Layout) -> PathBuf {
        if self.id == 0 {
            layout.default_instance()
        } else {
            layout.data.join("instances").join(self.id.to_string())
        }
    }
}

fn valid_name(name: &str) -> bool {
    (1..=32).contains(&name.chars().count()) && !name.chars().any(char::is_control)
}

pub(super) fn list(root: &Path) -> std::io::Result<Vec<Instance>> {
    let mut found = vec![Instance {
        id: 0,
        name: "默认实例".into(),
    }];
    let dirs = match fs::read_dir(root.join("instances")) {
        Ok(dirs) => dirs,
        Err(e) if e.kind() == ErrorKind::NotFound => return Ok(found),
        Err(e) => return Err(e),
    };
    for entry in dirs {
        let entry = entry?;
        if !entry.file_type()?.is_dir() {
            continue;
        }
        let raw = entry.file_name();
        let Some(id) = raw.to_str().and_then(|id| id.parse::<u32>().ok()) else {
            continue;
        };
        if id == 0 || raw != id.to_string().as_str() {
            continue;
        }
        let Ok(name) = fs::read_to_string(entry.path().join("name.txt")) else {
            continue;
        };
        if valid_name(&name) {
            found.push(Instance { id, name });
        }
    }
    found.sort_unstable_by_key(|item| item.id);
    Ok(found)
}

pub(super) fn create(root: &Path, name: &str) -> Result<u32, String> {
    let name = name.trim();
    if !valid_name(name) {
        return Err("实例名称需为 1–32 个字符，且不能包含换行等控制字符。".into());
    }
    let found = list(root).map_err(|e| e.to_string())?;
    if found
        .iter()
        .any(|item| item.name.eq_ignore_ascii_case(name))
    {
        return Err("已存在同名实例。".into());
    }
    let base = root.join("instances");
    fs::create_dir_all(&base).map_err(|e| e.to_string())?;
    for id in 1..=u32::MAX {
        let dir = base.join(id.to_string());
        match fs::create_dir(&dir) {
            Ok(()) => {
                if let Err(e) = fs::write(dir.join("name.txt"), name) {
                    let _ = fs::remove_file(dir.join("name.txt"));
                    let _ = fs::remove_dir(&dir);
                    return Err(e.to_string());
                }
                return Ok(id);
            }
            Err(e) if e.kind() == ErrorKind::AlreadyExists => continue,
            Err(e) => return Err(e.to_string()),
        }
    }
    Err("无法分配实例编号。".into())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn instance_names_are_labels_not_paths_and_default_stays_in_place() {
        let root = std::env::temp_dir().join(format!("nextmc-instances-{}", std::process::id()));
        fs::create_dir(&root).unwrap();
        fs::create_dir(root.join("offline-instance")).unwrap();
        let old_save = root.join("offline-instance").join("existing-save");
        fs::write(&old_save, "old world").unwrap();
        assert_eq!(create(&root, " 测试世界 ").unwrap(), 1);
        assert_eq!(create(&root, "../other").unwrap(), 2);
        assert!(create(&root, "测试世界").is_err());
        assert!(create(&root, "\n ").is_err());
        assert_eq!(
            list(&root)
                .unwrap()
                .iter()
                .map(|i| i.id)
                .collect::<Vec<_>>(),
            [0, 1, 2]
        );
        assert_eq!(
            fs::read_to_string(root.join("instances/2/name.txt")).unwrap(),
            "../other"
        );
        assert!(!root.join("other").exists());
        assert_eq!(fs::read_to_string(old_save).unwrap(), "old world");
        fs::remove_dir_all(root).unwrap();
    }
}
