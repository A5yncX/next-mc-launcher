use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::ptr::{null, null_mut};
use windows_sys::Win32::{
    Foundation::LocalFree,
    Security::Cryptography::{
        CryptProtectData, CryptUnprotectData, CRYPTPROTECT_UI_FORBIDDEN, CRYPT_INTEGER_BLOB,
    },
};

pub(super) const MAX_TOKEN: usize = 32 * 1024;
const MAX_BLOB: usize = MAX_TOKEN + 8192;

pub(super) struct Store(PathBuf);

pub(super) struct Saved {
    pub(super) refresh: String,
    encrypted: Vec<u8>,
}

impl Store {
    pub(super) fn new(data: &Path) -> Self {
        Self(data.join("microsoft-login.dpapi"))
    }

    fn encrypted(&self) -> io::Result<Option<Vec<u8>>> {
        let file = match File::open(&self.0) {
            Ok(file) => file,
            Err(e) if e.kind() == io::ErrorKind::NotFound => return Ok(None),
            Err(e) => return Err(e),
        };
        let mut bytes = Vec::new();
        file.take((MAX_BLOB + 1) as u64).read_to_end(&mut bytes)?;
        if bytes.is_empty() || bytes.len() > MAX_BLOB {
            return Err(invalid());
        }
        Ok(Some(bytes))
    }

    pub(super) fn exists(&self) -> bool {
        self.0.is_file()
    }

    pub(super) fn load(&self) -> io::Result<Option<Saved>> {
        let Some(encrypted) = self.encrypted()? else {
            return Ok(None);
        };
        let refresh = String::from_utf8(crypt(&encrypted, false)?).map_err(|_| invalid())?;
        if !valid_token(&refresh) {
            return Err(invalid());
        }
        Ok(Some(Saved { refresh, encrypted }))
    }

    fn lock(&self) -> io::Result<File> {
        fs::create_dir_all(self.0.parent().unwrap())?;
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(self.0.with_extension("lock"))?;
        file.try_lock().map_err(io::Error::from)?;
        Ok(file)
    }

    pub(super) fn save(&self, refresh: &str, previous: Option<&Saved>) -> io::Result<bool> {
        let _lock = self.lock()?;
        if let Some(saved) = previous {
            if self.encrypted()?.as_deref() != Some(&saved.encrypted) {
                return Ok(false);
            }
            if saved.refresh == refresh {
                return Ok(true);
            }
        }
        if !valid_token(refresh) {
            return Err(invalid());
        }
        let encrypted = crypt(refresh.as_bytes(), true)?;
        let partial = self.0.with_extension("tmp");
        let result = (|| {
            let mut file = File::create(&partial)?;
            file.write_all(&encrypted)?;
            file.sync_all()?;
            drop(file);
            fs::rename(&partial, &self.0)
        })();
        if result.is_err() {
            let _ = fs::remove_file(&partial);
        }
        result.map(|()| true)
    }

    pub(super) fn forget(&self) -> io::Result<()> {
        let _lock = self.lock()?;
        for path in [&self.0, &self.0.with_extension("tmp")] {
            match fs::remove_file(path) {
                Ok(()) => {}
                Err(e) if e.kind() == io::ErrorKind::NotFound => {}
                Err(e) => return Err(e),
            }
        }
        Ok(())
    }
}

fn invalid() -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, "invalid saved sign-in")
}

fn valid_token(value: &str) -> bool {
    !value.is_empty() && value.len() <= MAX_TOKEN && value.bytes().all(|b| b.is_ascii_graphic())
}

fn crypt(bytes: &[u8], protect: bool) -> io::Result<Vec<u8>> {
    let input = CRYPT_INTEGER_BLOB {
        cbData: bytes.len() as u32,
        pbData: bytes.as_ptr().cast_mut(),
    };
    let mut output = CRYPT_INTEGER_BLOB::default();
    let flags = CRYPTPROTECT_UI_FORBIDDEN;
    // DPAPI allocates the output; without LOCAL_MACHINE it is protected for this Windows user.
    unsafe {
        let ok = if protect {
            CryptProtectData(&input, null(), null(), null(), null(), flags, &mut output)
        } else {
            CryptUnprotectData(
                &input,
                null_mut(),
                null(),
                null(),
                null(),
                flags,
                &mut output,
            )
        };
        if ok == 0 {
            return Err(io::Error::last_os_error());
        }
        let result = if output.pbData.is_null() || output.cbData as usize > MAX_BLOB {
            Err(invalid())
        } else {
            Ok(std::slice::from_raw_parts(output.pbData, output.cbData as usize).to_vec())
        };
        LocalFree(output.pbData.cast());
        result
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn current_user_can_restore_rotate_and_forget_an_encrypted_token() {
        let dir = std::env::temp_dir().join(format!(
            "nextmc-auth-test-{}-{}",
            std::process::id(),
            crate::auth::now()
        ));
        fs::create_dir(&dir).unwrap();
        let store = Store::new(&dir);
        let token = "fixture-refresh-token";
        assert!(store.save(token, None).unwrap());
        assert!(!fs::read(&store.0)
            .unwrap()
            .windows(token.len())
            .any(|w| w == token.as_bytes()));
        let previous = store.load().unwrap().unwrap();
        assert_eq!(previous.refresh, token);
        assert!(store.save("next-fixture-token", Some(&previous)).unwrap());
        let rotated = store.load().unwrap().unwrap();
        assert_eq!(rotated.refresh, "next-fixture-token");
        assert!(!store.save(token, Some(&previous)).unwrap());
        fs::write(store.0.with_extension("tmp"), b"interrupted-write").unwrap();
        store.forget().unwrap();
        assert!(!store.0.with_extension("tmp").exists());
        assert!(!store.save(token, Some(&rotated)).unwrap());
        assert!(store.load().unwrap().is_none());
        fs::write(&store.0, b"plaintext-is-not-imported").unwrap();
        assert!(store.load().is_err());
        fs::remove_dir_all(dir).unwrap();
    }
}
