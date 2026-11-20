//! Offline CLI and explicit Microsoft device-code session export.

mod auth;
mod layout;
mod play;

use std::io::Write;
use std::sync::atomic::AtomicBool;

const SAVE: &str = "mc-login.json";

#[derive(serde::Deserialize, serde::Serialize)]
struct Saved {
    #[serde(flatten)]
    session: auth::Session,
    refresh_token: String,
}

fn write_private(path: &str, contents: &str, new: bool) -> std::io::Result<()> {
    let mut options = std::fs::OpenOptions::new();
    options.write(true);
    if new {
        options.create_new(true);
    } else {
        options.create(true).truncate(true);
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    options.open(path)?.write_all(contents.as_bytes())
}

fn main() {
    let mut args = std::env::args().skip(1);
    let mut arg = args.next();
    if matches!(arg.as_deref(), None | Some("play")) {
        std::process::exit(play::run(args).unwrap_or_else(|e| {
            eprintln!("mc-login: {e}");
            1
        }));
    }
    if arg.as_deref() == Some("login") {
        arg = args.next();
    }
    let mut client_id = std::env::var("HORIZON_MSA_CLIENT_ID").ok();
    let mut session_file = None;
    let mut print_session = false;
    while let Some(a) = arg {
        match a.as_str() {
            "--client-id" => client_id = Some(required_value(&a, args.next())),
            "--session-file" => session_file = Some(required_value(&a, args.next())),
            "--print-session" => print_session = true,
            "--help" | "-h" => {
                println!(
                    "mc-login: Offline play and Microsoft sign-in for Minecraft.\n\n\
                     mc-login (no arguments)  Start offline single-player.\n\
                     {}  Start offline with optional paths.\n\n\
                     mc-login login [OPTIONS]  Sign in with Microsoft.\n\
                     --client-id ID    Developer override for the built-in app registration\n\
                     --session-file P  Write the session JSON for `horizon-client --session-file P`\n\
                     --print-session   Print the secret session JSON to stdout\n\n\
                     CLI stores a refresh token in plaintext in {SAVE} (delete it to sign out).",
                    play::USAGE
                );
                return;
            }
            other => fail(2, &format!("unknown argument {other}")),
        }
        arg = args.next();
    }
    let id = client_id
        .as_deref()
        .map(str::trim)
        .filter(|id| !id.is_empty())
        .unwrap_or(auth::CLIENT_ID);
    if !auth::valid_client_id(id) {
        fail(
            2,
            "expected the approved Azure application (client) ID in GUID format",
        );
    }
    let progress = |s: &str| eprintln!("{s}");
    let cached = std::fs::read_to_string(SAVE)
        .ok()
        .and_then(|s| serde_json::from_str::<Saved>(&s).ok());
    let renewal = cached.and_then(
        |saved| match auth::renew(id, &saved.refresh_token, &progress) {
            Ok((session, refresh)) => Some((session, Some(refresh.unwrap_or(saved.refresh_token)))),
            Err(e) => {
                eprintln!("mc-login: {e}\nFalling back to browser sign-in.");
                None
            }
        },
    );
    let (session, refresh) = renewal.unwrap_or_else(|| {
        auth::sign_in(
            id,
            true,
            &AtomicBool::new(false),
            &|c| {
                eprintln!(
                    "Open {} and enter the code: {}",
                    c.verification_uri, c.user_code
                );
            },
            &progress,
        )
        .unwrap_or_else(|e| fail(1, &e))
    });
    // A cancelled or failed ownership/profile check never reaches export or cache writes.
    if !session.usable() {
        fail(1, "Minecraft session expired. Please try signing in again.");
    }
    let body = session.body();
    eprintln!(
        "Signed in: {} ({})",
        session.account.name, session.account.uuid
    );
    if let Some(refresh_token) = refresh {
        let saved = Saved {
            session,
            refresh_token,
        };
        if let Err(e) = write_private(SAVE, &serde_json::to_string(&saved).unwrap(), false) {
            eprintln!("mc-login: couldn't save sign-in ({e}); the browser will be needed again.");
        }
    }
    if let Some(path) = session_file {
        if let Err(e) = write_private(&path, &body, true) {
            fail(1, &format!("couldn't write {path}: {e}"));
        }
        eprintln!("Session written to {path} (the game reads and deletes it).");
    }
    if print_session {
        println!("{body}");
    }
}

fn required_value(flag: &str, value: Option<String>) -> String {
    value
        .filter(|v| !v.is_empty() && !v.starts_with("--"))
        .unwrap_or_else(|| fail(2, &format!("{flag} requires a value")))
}

fn fail(code: i32, message: &str) -> ! {
    eprintln!("mc-login: {message}");
    std::process::exit(code);
}
