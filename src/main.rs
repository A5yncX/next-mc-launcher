//! A minimal Minecraft login client: the Microsoft device-code flow, Xbox Live, XSTS,
//! the Minecraft services, the ownership check and the profile — the same flow the
//! Horizon launcher runs (horizon-rust/horizon, launcher/src/account.rs), without the
//! launcher: no keychain, no telemetry, no shop, one file of code.
//!
//! The client ID is configuration, not code: Horizon's own registration belongs to
//! Horizon (docs/forking.md forbids forks from using it). Set HORIZON_MSA_CLIENT_ID,
//! or pass --client-id, with your own Azure app registration (docs/microsoft-account.md
//! in the Horizon repo walks through creating one; Mojang must approve it for the
//! Minecraft API step).
//!
//! Tokens are cached in plaintext in `mc-login.json` in the working directory.
//! `--session-file` and `--print-session` explicitly export a token; keep those outputs private.

use serde_json::{json, Value};
use std::io::Write;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

const SCOPE: &str = "XboxLive.signin offline_access";
const MS_OAUTH: &str = "https://login.microsoftonline.com/consumers/oauth2/v2.0";
const XBOX_USER: &str = "https://user.auth.xboxlive.com/user/authenticate";
const XSTS: &str = "https://xsts.auth.xboxlive.com/xsts/authorize";
const MC: &str = "https://api.minecraftservices.com";

fn now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |d| d.as_secs())
}

fn field(v: &Value, key: &str) -> Option<String> {
    v.get(key).and_then(Value::as_str).map(str::to_owned)
}

/// Send an HTTPS request and return its status and parsed response.
fn send(method: &str, url: &str, body: Option<Body>, bearer: Option<&str>) -> Result<(u16, Value), String> {
    let mut request = ureq::AgentBuilder::new()
        .timeout(Duration::from_secs(30))
        .build()
        .request(method, url);
    if let Some(token) = bearer {
        request = request.set("Authorization", &format!("Bearer {token}"));
    }
    let request = match body {
        Some(Body::Form(pairs)) => request.send_form(pairs),
        Some(Body::Json(v)) => request.send_json(serde_json::to_value(v).unwrap()),
        None => request.call(),
    };
    match request {
        Ok(response) => Ok((response.status(), parsed(response))),
        Err(ureq::Error::Status(code, response)) => Ok((code, parsed(response))),
        Err(e) => Err(format!("network: {e}")),
    }
}

/// Parse the response as JSON if possible.
fn parsed(response: ureq::Response) -> Value {
    response
        .into_string()
        .ok()
        .and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or(Value::String(String::new()))
}

enum Body<'a> {
    Form(&'a [(&'a str, &'a str)]),
    Json(serde_json::Value),
}

fn oauth_error(v: &Value) -> String {
    match v.get("error").and_then(Value::as_str) {
        Some("authorization_declined") => "Sign-in was declined in the browser.".into(),
        Some("expired_token") => "The sign-in code expired. Start again.".into(),
        Some("bad_verification_code") => "The sign-in code was not recognised.".into(),
        Some("invalid_grant") => "Your Microsoft sign-in expired. Sign in again.".into(),
        Some("invalid_client" | "unauthorized_client") => {
            "Microsoft refused this app registration (client ID).".into()
        }
        Some(other) => format!("Microsoft sign-in failed ({other})."),
        None => "Microsoft sign-in failed.".into(),
    }
}

// ----- The device-code flow ------------------------------------------------------------------

struct DeviceCode {
    user_code: String,
    verification_uri: String,
    interval: u64,
    expires_at: u64,
    device_code: String,
}

fn device_code(client_id: &str) -> Result<DeviceCode, String> {
    let (status, v) = send(
        "POST",
        &format!("{MS_OAUTH}/devicecode"),
        Some(Body::Form(&[("client_id", client_id), ("scope", SCOPE)])),
        None,
    )?;
    match (status, field(&v, "user_code"), field(&v, "device_code")) {
        (200, Some(user_code), Some(device_code)) => Ok(DeviceCode {
            user_code,
            verification_uri: field(&v, "verification_uri")
                .unwrap_or_else(|| "https://www.microsoft.com/link".into()),
            interval: v.get("interval").and_then(Value::as_u64).unwrap_or(5).clamp(1, 60),
            expires_at: now() + v.get("expires_in").and_then(Value::as_u64).unwrap_or(900).min(3600),
            device_code,
        }),
        _ => Err(oauth_error(&v)),
    }
}

struct MsTokens {
    access: String,
    refresh: String,
}

fn ms_tokens(status: u16, v: &Value) -> Result<MsTokens, String> {
    match (status, field(v, "access_token"), field(v, "refresh_token")) {
        (200, Some(access), Some(refresh)) => Ok(MsTokens { access, refresh }),
        _ => Err(oauth_error(v)),
    }
}

fn poll(client_id: &str, code: &DeviceCode) -> Result<Option<MsTokens>, String> {
    let (status, v) = send(
        "POST",
        &format!("{MS_OAUTH}/token"),
        Some(Body::Form(&[
            ("grant_type", "urn:ietf:params:oauth:grant-type:device_code"),
            ("client_id", client_id),
            ("device_code", &code.device_code),
        ])),
        None,
    )?;
    match v.get("error").and_then(Value::as_str) {
        Some("authorization_pending") => Ok(None),
        Some("slow_down") => Ok(None),
        _ => ms_tokens(status, &v).map(Some),
    }
}

fn wait_for_sign_in(client_id: &str, code: &DeviceCode) -> Result<MsTokens, String> {
    let mut interval = code.interval;
    loop {
        std::thread::sleep(Duration::from_secs(interval));
        if now() > code.expires_at {
            return Err("The sign-in code expired. Start again.".into());
        }
        match poll(client_id, code)? {
            None => interval = (interval + 5).min(60),
            Some(tokens) => return Ok(tokens),
        }
    }
}

fn refresh_ms(client_id: &str, refresh: &str) -> Result<MsTokens, String> {
    let (status, v) = send(
        "POST",
        &format!("{MS_OAUTH}/token"),
        Some(Body::Form(&[
            ("grant_type", "refresh_token"),
            ("client_id", client_id),
            ("refresh_token", refresh),
            ("scope", SCOPE),
        ])),
        None,
    )?;
    ms_tokens(status, &v)
}

// ----- Xbox Live, XSTS, Minecraft ------------------------------------------------------------

fn xsts_error(code: u64) -> String {
    match code {
        2148916233 => "This Microsoft account has no Xbox profile yet. Sign in once at xbox.com first.".into(),
        2148916235 => "Xbox Live is not available in your country or region.".into(),
        2148916236 | 2148916237 => "This account needs adult verification on xbox.com first.".into(),
        2148916238 => "This is a child account: an adult has to add it to a Microsoft family first.".into(),
        other => format!("Xbox Live refused the sign-in (error {other})."),
    }
}

struct Minecraft {
    token: String,
    expires_at: u64,
    xuid: Option<String>,
}

fn minecraft_login(ms_access: &str, progress: &dyn Fn(&str)) -> Result<Minecraft, String> {
    progress("Xbox Live");
    let (status, xbl) = send(
        "POST",
        XBOX_USER,
        Some(Body::Json(json!({
            "Properties": {
                "AuthMethod": "RPS",
                "SiteName": "user.auth.xboxlive.com",
                "RpsTicket": format!("d={ms_access}"),
            },
            "RelyingParty": "http://auth.xboxlive.com",
            "TokenType": "JWT",
        }))),
        None,
    )?;
    let xbl_token = field(&xbl, "Token").filter(|_| status == 200)
        .ok_or("Xbox Live refused the sign-in.")?;
    let (status, xsts) = send(
        "POST",
        XSTS,
        Some(Body::Json(json!({
            "Properties": { "SandboxId": "RETAIL", "UserTokens": [xbl_token] },
            "RelyingParty": "rp://api.minecraftservices.com/",
            "TokenType": "JWT",
        }))),
        None,
    )?;
    if let Some(code) = xsts.get("XErr").and_then(Value::as_u64) {
        return Err(xsts_error(code));
    }
    let claims = xsts.pointer("/DisplayClaims/xui/0");
    let (Some(xsts_token), Some(uhs)) = (
        field(&xsts, "Token").filter(|_| status == 200),
        claims.and_then(|c| field(c, "uhs")),
    ) else {
        return Err("Xbox Live refused the sign-in.".into());
    };
    let xuid = claims.and_then(|c| field(c, "xid"));
    progress("Minecraft");
    let (token, expires_in) = minecraft_token(&format!("XBL3.0 x={uhs};{xsts_token}"))?;
    Ok(Minecraft { token, expires_at: now() + expires_in.min(7 * 86_400), xuid })
}

/// `launcher/login` first (it names the profile), `login_with_xbox` as the fallback — the
/// same order and reason as Horizon's launcher (launcher/src/account.rs, minecraft_token).
fn minecraft_token(xtoken: &str) -> Result<(String, u64), String> {
    let lifetime = |v: &Value| v.get("expires_in").and_then(Value::as_u64).unwrap_or(86400);
    let (status, v) = send(
        "POST",
        &format!("{MC}/launcher/login"),
        Some(Body::Json(json!({ "xtoken": xtoken, "platform": "PC_LAUNCHER" }))),
        None,
    )?;
    if status == 200 {
        if let Some(token) = field(&v, "access_token") {
            return Ok((token, lifetime(&v)));
        }
    }
    let (status, mc) = send(
        "POST",
        &format!("{MC}/authentication/login_with_xbox"),
        Some(Body::Json(json!({ "identityToken": xtoken }))),
        None,
    )?;
    match (status, field(&mc, "access_token")) {
        (200, Some(token)) => Ok((token, lifetime(&mc))),
        (403, _) => Err("The Minecraft services refused this app: it is not approved by Mojang yet (aka.ms/mce-reviewappid).".into()),
        (429, _) => Err("Too many sign-ins in a short time. Wait a minute.".into()),
        _ => Err("The Minecraft services refused the sign-in.".into()),
    }
}

fn owns_game(token: &str) -> Result<bool, String> {
    let (status, v) = send(
        "GET",
        &format!("{MC}/entitlements/mcstore"),
        None,
        Some(token),
    )?;
    if status != 200 {
        return Err("Could not check which games this account owns.".into());
    }
    Ok(v.get("items").and_then(Value::as_array).is_some_and(|items| {
        items.iter().any(|i| {
            matches!(
                i.get("name").and_then(Value::as_str),
                Some("game_minecraft" | "product_minecraft")
            )
        })
    }))
}

// ----- Profile, save file, session file ------------------------------------------------------

/// The profile as shown to the player; no secrets.
#[derive(Clone, Debug, serde::Serialize, serde::Deserialize)]
struct Account {
    uuid: String,
    name: String,
    #[serde(default)]
    skin: Option<(String, String)>,
}

fn profile(token: &str) -> Result<Option<Account>, String> {
    let (status, v) = send("GET", &format!("{MC}/minecraft/profile"), None, Some(token))?;
    if status == 404 {
        return Ok(None);
    }
    let (Some(uuid), Some(name)) = (field(&v, "id"), field(&v, "name")) else {
        return Err("Could not read the Minecraft profile.".into());
    };
    let active = |key: &str| {
        v.get(key).and_then(Value::as_array).and_then(|list| {
            list.iter().find(|s| s.get("state").and_then(Value::as_str) == Some("ACTIVE"))
        }).cloned()
    };
    Ok(Some(Account {
        uuid: uuid.replace('-', "").to_lowercase(),
        name,
        skin: active("skins").and_then(|s| Some((field(&s, "url")?, field(&s, "variant").unwrap_or_default().to_lowercase()))),
    }))
}

/// What mc-login.json keeps so the browser is needed once.
#[derive(serde::Serialize, serde::Deserialize)]
struct Saved {
    account: Account,
    refresh_token: String,
    minecraft_token: String,
    minecraft_expires_at: u64,
    #[serde(default)]
    xuid: Option<String>,
}

const SAVE: &str = "mc-login.json";

fn load_saved() -> Option<Saved> {
    std::fs::read_to_string(SAVE).ok().and_then(|s| serde_json::from_str(&s).ok())
}

fn save(saved: &Saved) -> Result<(), String> {
    let mut options = std::fs::OpenOptions::new();
    options.write(true).create(true).truncate(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(SAVE).map_err(|e| e.to_string())?;
    file.write_all(serde_json::to_string(saved).unwrap().as_bytes())
        .map_err(|e| e.to_string())
}

/// A session file as `horizon-client --session-file PATH` reads: read once, deleted at once,
/// refused when older than two minutes.
fn write_session_file(path: &str, saved: &Saved) -> Result<(), String> {
    let body = json!({
        "name": saved.account.name,
        "uuid": saved.account.uuid,
        "access_token": saved.minecraft_token,
        "user_type": "msa",
        "xuid": saved.xuid,
    });
    let mut options = std::fs::OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(path).map_err(|e| e.to_string())?;
    file.write_all(body.to_string().as_bytes()).map_err(|e| e.to_string())
}

// ----- Main -----------------------------------------------------------------------------------

fn main() {
    let mut args = std::env::args().skip(1);
    let mut client_id = std::env::var("HORIZON_MSA_CLIENT_ID").ok().filter(|s| !s.trim().is_empty());
    let mut session_file: Option<String> = None;
    let mut print_session = false;
    let mut arg = args.next();
    while let Some(a) = arg {
        match a.as_str() {
            "--client-id" => client_id = args.next().map(|v| v.trim().to_owned()),
            "--session-file" => session_file = args.next(),
            "--print-session" => print_session = true,
            "--help" | "-h" => {
                println!(
                    "mc-login: Microsoft sign-in for Minecraft, without a launcher.\n\n\
                     --client-id ID    Your Azure app registration (or HORIZON_MSA_CLIENT_ID)\n\
                     --session-file P  Write the session JSON for `horizon-client --session-file P`\n\
                     --print-session   Print the session JSON to stdout\n\n\
                     Signs in with the device-code flow, checks ownership, prints the profile,\n\
                     keeps the refresh token in {SAVE} (delete it to sign out)."
                );
                return;
            }
            other => {
                eprintln!("mc-login: unknown argument {other}");
                std::process::exit(2);
            }
        }
        arg = args.next();
    }
    let Some(client_id) = client_id else {
        eprintln!("mc-login: no client ID. Pass --client-id or set HORIZON_MSA_CLIENT_ID.");
        eprintln!("Create an Azure app registration (personal accounts, public client flows);");
        eprintln!("Mojang must approve it: https://aka.ms/mce-reviewappid");
        std::process::exit(2);
    };

    let saved: Option<Saved> = load_saved();
    let result = match saved {
        Some(mut s) => {
            println!("Saved sign-in: {} ({}). Renewing…", s.account.name, s.account.uuid);
            let renewed = refresh_ms(&client_id, &s.refresh_token)
                .and_then(|ms| minecraft_login(&ms.access, &|_| {}).map(|mc| (ms, mc)));
            match renewed {
                Ok((ms, mc)) => {
                    s.refresh_token = ms.refresh;
                    s.minecraft_token = mc.token;
                    s.minecraft_expires_at = mc.expires_at;
                    s.xuid = mc.xuid;
                    Ok(s)
                }
                Err(e) => {
                    eprintln!("mc-login: {e}");
                    eprintln!("Falling back to the browser sign-in.");
                    sign_in_fresh(&client_id)
                }
            }
        }
        None => sign_in_fresh(&client_id),
    };
    let Ok(mut saved) = result else {
        eprintln!("mc-login: sign-in failed.");
        std::process::exit(1);
    };

    println!("Checking ownership…");
    match owns_game(&saved.minecraft_token) {
        Ok(true) => {}
        Ok(false) => {
            eprintln!("mc-login: this account doesn't own Minecraft: Java Edition.");
            std::process::exit(1);
        }
        Err(e) => {
            eprintln!("mc-login: {e} (continuing; the game may refuse online-mode servers)");
        }
    }
    if let Ok(Some(p)) = profile(&saved.minecraft_token) {
        if p.uuid != saved.account.uuid {
            saved.account = p.clone();
        }
        println!();
        println!("Signed in: {} ({})", p.name, p.uuid);
        if let Some((url, variant)) = &p.skin {
            println!("Skin: {variant} — {url}");
        }
        println!("Token expires at epoch {} (renewed next run).", saved.minecraft_expires_at);
    }

    if let Err(e) = save(&saved) {
        eprintln!("mc-login: couldn't save the sign-in ({e}); the browser will be needed again.");
    }
    if let Some(path) = session_file {
        match write_session_file(&path, &saved) {
            Ok(()) => println!("Session written to {path} (the game reads and deletes it)."),
            Err(e) => {
                eprintln!("mc-login: couldn't write {path}: {e}");
                std::process::exit(1);
            }
        }
    }
    if print_session {
        println!(
            "{}",
            json!({
                "name": saved.account.name,
                "uuid": saved.account.uuid,
                "access_token": saved.minecraft_token,
                "user_type": "msa",
                "xuid": saved.xuid,
            })
        );
    }
}

fn sign_in_fresh(client_id: &str) -> Result<Saved, String> {
    let code = match device_code(client_id) {
        Ok(code) => code,
        Err(e) => {
            eprintln!("mc-login: {e}");
            return Err(e);
        }
    };
    println!("Sign in with Microsoft:");
    println!("  1. Open {}", code.verification_uri);
    println!("  2. Enter the code: {}", code.user_code);
    println!("Waiting (the code expires at epoch {})…", code.expires_at);
    let ms = wait_for_sign_in(client_id, &code)?;
    let mc = minecraft_login(&ms.access, &|phase| println!("…{phase}"))?;
    let account = profile(&mc.token)?.ok_or(
        "This account has no Minecraft profile yet. Create one at minecraft.net, then sign in again.",
    )?;
    Ok(Saved {
        account,
        refresh_token: ms.refresh,
        minecraft_token: mc.token,
        minecraft_expires_at: mc.expires_at,
        xuid: mc.xuid,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn oauth_errors_have_a_reason() {
        let v = serde_json::from_str::<Value>(
            r#"{"error":"unauthorized_client","error_description":"AADSTS700038"}"#,
        )
        .unwrap();
        assert_eq!(
            oauth_error(&v),
            "Microsoft refused this app registration (client ID)."
        );
        assert_eq!(oauth_error(&Value::Null), "Microsoft sign-in failed.");
    }

    #[test]
    fn xsts_errors_name_the_fix() {
        assert!(xsts_error(2148916233).contains("Xbox profile"));
        assert!(xsts_error(2148916238).contains("child account"));
    }

    #[test]
    fn session_file_body_is_horizon_json() {
        let saved = Saved {
            account: Account { uuid: "069a79f444e94726a5befca90e38aaf5".into(), name: "Alex".into(), skin: None },
            refresh_token: "r".into(),
            minecraft_token: "t".into(),
            minecraft_expires_at: 0,
            xuid: Some("123".into()),
        };
        let body = json!({
            "name": saved.account.name,
            "uuid": saved.account.uuid,
            "access_token": saved.minecraft_token,
            "user_type": "msa",
            "xuid": saved.xuid,
        });
        assert_eq!(body["user_type"], "msa");
        assert_eq!(body["name"], "Alex");
        assert_eq!(body["uuid"], "069a79f444e94726a5befca90e38aaf5");
    }
}
