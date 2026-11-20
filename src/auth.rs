use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

const MS: &str = "https://login.microsoftonline.com/consumers/oauth2/v2.0";
const MC: &str = "https://api.minecraftservices.com";
const SCOPE: &str = "XboxLive.signin offline_access";
// This public OAuth client identifier is not a client secret.
pub(crate) const CLIENT_ID: &str = "aa353f50-9f78-46e4-911b-6ac546007628";
pub(crate) const CANCELLED: &str = "已取消 Microsoft 登录。";

pub(crate) fn now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |d| d.as_secs())
}

pub(crate) fn valid_client_id(id: &str) -> bool {
    id.len() == 36
        && id.bytes().enumerate().all(|(i, b)| {
            if matches!(i, 8 | 13 | 18 | 23) {
                b == b'-'
            } else {
                b.is_ascii_hexdigit()
            }
        })
}

fn field<'a>(v: &'a Value, key: &str) -> Option<&'a str> {
    v.get(key)?.as_str().filter(|s| !s.is_empty())
}

struct Http(ureq::Agent);

impl Http {
    fn new() -> Self {
        Self(
            ureq::AgentBuilder::new()
                .redirects(0)
                .timeout(Duration::from_secs(15))
                .build(),
        )
    }

    fn response(result: Result<ureq::Response, ureq::Error>) -> Result<(u16, Value), String> {
        let response = match result {
            Ok(r) | Err(ureq::Error::Status(_, r)) => r,
            Err(_) => {
                return Err(
                    "Network request failed. Check your network connection and try again.".into(),
                )
            }
        };
        let status = response.status();
        use std::io::Read;
        let body = serde_json::from_reader(response.into_reader().take(1024 * 1024))
            .unwrap_or(Value::Null);
        Ok((status, body))
    }

    fn form(&self, url: &str, fields: &[(&str, &str)]) -> Result<(u16, Value), String> {
        Self::response(self.0.post(url).send_form(fields))
    }

    fn post(&self, url: &str, body: Value) -> Result<(u16, Value), String> {
        Self::response(self.0.post(url).send_json(body))
    }

    fn get(&self, path: &str, token: &str) -> Result<(u16, Value), String> {
        Self::response(
            self.0
                .get(&format!("{MC}/{path}"))
                .set("Authorization", &format!("Bearer {token}"))
                .call(),
        )
    }
}

fn oauth_error(v: &Value) -> String {
    match field(v, "error") {
        Some("authorization_declined" | "access_denied") => "Sign-in was declined in the browser.",
        Some("expired_token") => "The sign-in code expired. Start again.",
        Some("bad_verification_code") => "The sign-in code was not recognised.",
        Some("invalid_grant") => "Your Microsoft sign-in expired. Sign in again.",
        Some("invalid_client" | "unauthorized_client") => {
            "Microsoft refused this app registration (client ID)."
        }
        _ => "Microsoft sign-in failed.",
    }
    .into()
}

#[derive(Serialize)]
pub(crate) struct Challenge {
    pub(crate) user_code: String,
    pub(crate) verification_uri: &'static str,
}

fn verification_uri(value: Option<&str>) -> Result<&'static str, String> {
    match value {
        None | Some("https://www.microsoft.com/link") => Ok("https://www.microsoft.com/link"),
        Some("https://microsoft.com/devicelogin" | "https://www.microsoft.com/devicelogin") => {
            Ok("https://www.microsoft.com/devicelogin")
        }
        _ => Err("Microsoft returned an unexpected device sign-in address.".into()),
    }
}

fn check_cancel(cancel: &AtomicBool) -> Result<(), String> {
    if cancel.load(Ordering::Relaxed) {
        Err(CANCELLED.into())
    } else {
        Ok(())
    }
}

fn poll_delay(result: &Value, interval: &mut u64) -> bool {
    match field(result, "error") {
        Some("authorization_pending") => true,
        Some("slow_down") => {
            *interval += 5;
            true
        }
        _ => false,
    }
}

pub(crate) fn sign_in(
    id: &str,
    remember: bool,
    cancel: &AtomicBool,
    challenge: &dyn Fn(Challenge),
    progress: &dyn Fn(&str),
) -> Result<(Session, Option<String>), String> {
    if !valid_client_id(id) {
        return Err("请输入 Azure 的应用程序（客户端）ID，格式为 GUID。".into());
    }
    let http = Http::new();
    check_cancel(cancel)?;
    let scope = if remember { SCOPE } else { "XboxLive.signin" };
    let (status, device) = http.form(
        &format!("{MS}/devicecode"),
        &[("client_id", id), ("scope", scope)],
    )?;
    check_cancel(cancel)?;
    if status != 200 {
        return Err(oauth_error(&device));
    }
    let code = field(&device, "device_code").ok_or("Microsoft did not return a device code.")?;
    let user_code = field(&device, "user_code")
        .filter(|code| {
            code.len() <= 32 && code.bytes().all(|c| c.is_ascii_alphanumeric() || c == b'-')
        })
        .ok_or("Microsoft did not return a valid user code.")?;
    let mut interval = device["interval"].as_u64().unwrap_or(5).clamp(1, 3600);
    let deadline = Instant::now()
        + Duration::from_secs(device["expires_in"].as_u64().unwrap_or(900).min(3600));
    challenge(Challenge {
        user_code: user_code.into(),
        verification_uri: verification_uri(field(&device, "verification_uri"))?,
    });
    loop {
        let next = Instant::now() + Duration::from_secs(interval);
        loop {
            check_cancel(cancel)?;
            let now = Instant::now();
            if now >= deadline {
                return Err("The sign-in code expired. Start again.".into());
            }
            if now >= next {
                break;
            }
            std::thread::sleep((deadline.min(next) - now).min(Duration::from_millis(100)));
        }
        let (status, result) = http.form(
            &format!("{MS}/token"),
            &[
                ("grant_type", "urn:ietf:params:oauth:grant-type:device_code"),
                ("client_id", id),
                ("device_code", code),
            ],
        )?;
        check_cancel(cancel)?;
        if poll_delay(&result, &mut interval) {
            continue;
        }
        return finish_token(&http, status, &result, cancel, progress);
    }
}

pub(crate) fn renew(
    id: &str,
    refresh: &str,
    progress: &dyn Fn(&str),
) -> Result<(Session, Option<String>), String> {
    let http = Http::new();
    let (status, response) = http.form(
        &format!("{MS}/token"),
        &[
            ("grant_type", "refresh_token"),
            ("client_id", id),
            ("refresh_token", refresh),
            ("scope", SCOPE),
        ],
    )?;
    finish_token(&http, status, &response, &AtomicBool::new(false), progress)
}

fn xsts_error(code: u64) -> String {
    match code {
        2148916233 => {
            "This Microsoft account has no Xbox profile yet. Sign in once at xbox.com first.".into()
        }
        2148916235 => "Xbox Live is not available in your country or region.".into(),
        2148916236 | 2148916237 => {
            "This account needs adult verification on xbox.com first.".into()
        }
        2148916238 => {
            "This is a child account: an adult has to add it to a Microsoft family first.".into()
        }
        other => format!("Xbox Live refused the sign-in (error {other})."),
    }
}

#[derive(Serialize, Deserialize)]
pub(crate) struct Account {
    pub(crate) uuid: String,
    pub(crate) name: String,
    #[serde(skip)]
    #[allow(dead_code, reason = "Only the GUI displays the Minecraft skin.")]
    pub(crate) skin_url: Option<String>,
}

#[derive(Serialize, Deserialize)]
pub(crate) struct Session {
    pub(crate) account: Account,
    minecraft_token: String,
    pub(crate) minecraft_expires_at: u64,
    xuid: Option<String>,
}

impl Session {
    pub(crate) fn usable(&self) -> bool {
        self.minecraft_expires_at > now().saturating_add(60)
    }

    pub(crate) fn body(&self) -> String {
        let mut value = json!({
            "name": self.account.name, "uuid": self.account.uuid, "access_token": self.minecraft_token, "user_type": "msa",
        });
        if let Some(xuid) = &self.xuid {
            value["xuid"] = json!(xuid);
        }
        value.to_string()
    }
}

fn finish_token(
    http: &Http,
    status: u16,
    result: &Value,
    cancel: &AtomicBool,
    progress: &dyn Fn(&str),
) -> Result<(Session, Option<String>), String> {
    let access = field(result, "access_token")
        .filter(|_| status == 200)
        .ok_or_else(|| oauth_error(result))?;
    check_cancel(cancel)?;
    progress("正在验证 Xbox Live…");
    let (status, xbl) = http.post("https://user.auth.xboxlive.com/user/authenticate", json!({
        "Properties": {"AuthMethod":"RPS", "SiteName":"user.auth.xboxlive.com", "RpsTicket":format!("d={access}")},
        "RelyingParty":"http://auth.xboxlive.com", "TokenType":"JWT",
    }))?;
    let xbl = field(&xbl, "Token")
        .filter(|_| status == 200)
        .ok_or("Xbox Live refused the sign-in.")?;
    check_cancel(cancel)?;
    let (status, xsts) = http.post("https://xsts.auth.xboxlive.com/xsts/authorize", json!({
        "Properties":{"SandboxId":"RETAIL", "UserTokens":[xbl]}, "RelyingParty":"rp://api.minecraftservices.com/", "TokenType":"JWT",
    }))?;
    if let Some(error) = xsts["XErr"].as_u64() {
        return Err(xsts_error(error));
    }
    let xsts_token = field(&xsts, "Token")
        .filter(|_| status == 200)
        .ok_or("Xbox Live refused the sign-in.")?;
    let claims = xsts
        .pointer("/DisplayClaims/xui/0")
        .ok_or("Xbox Live returned no account claims.")?;
    let uhs = field(claims, "uhs").ok_or("Xbox Live returned no user hash.")?;
    let proof = format!("XBL3.0 x={uhs};{xsts_token}");
    check_cancel(cancel)?;
    progress("正在获取 Minecraft 会话…");
    let (status, response) = http.post(
        &format!("{MC}/launcher/login"),
        json!({"xtoken": proof, "platform":"PC_LAUNCHER"}),
    )?;
    let (status, response) =
        if status == 429 || (status == 200 && field(&response, "access_token").is_some()) {
            (status, response)
        } else {
            check_cancel(cancel)?;
            http.post(
                &format!("{MC}/authentication/login_with_xbox"),
                json!({"identityToken": proof}),
            )?
        };
    let token = field(&response, "access_token")
        .filter(|t| status == 200 && t.len() <= 16_384 && t.bytes().all(|b| b.is_ascii_graphic()))
        .ok_or_else(|| match status {
            403 => "Minecraft API 拒绝了当前启动器。请更新启动器；若仍失败，请联系维护者。",
            429 => "登录请求过多，请稍候再试。",
            _ => "Minecraft services did not issue a valid session.",
        })?;
    let expires_at = now()
        + response["expires_in"]
            .as_u64()
            .filter(|&s| s > 60)
            .ok_or("Minecraft did not issue a usable session lifetime.")?
            .min(7 * 86_400);
    check_cancel(cancel)?;
    progress("正在检查 Java 版所有权与游戏档案…");
    let (status, owned) = http.get("entitlements/mcstore", token)?;
    ownership(status, &owned)?;
    check_cancel(cancel)?;
    let (status, profile) = http.get("minecraft/profile", token)?;
    let account = account(status, &profile)?;
    check_cancel(cancel)?;
    Ok((
        Session {
            account,
            minecraft_token: token.into(),
            minecraft_expires_at: expires_at,
            xuid: field(claims, "xid").map(str::to_owned),
        },
        field(result, "refresh_token").map(str::to_owned),
    ))
}

fn ownership(status: u16, response: &Value) -> Result<(), String> {
    let items = response["items"]
        .as_array()
        .filter(|_| status == 200)
        .ok_or("无法确认 Minecraft Java 版所有权；请稍后重试。")?;
    if !items.iter().any(|i| {
        matches!(
            field(i, "name"),
            Some("game_minecraft" | "product_minecraft")
        )
    }) {
        return Err("此账号未检测到 Minecraft Java 版所有权。".into());
    }
    Ok(())
}

fn account(status: u16, value: &Value) -> Result<Account, String> {
    if status == 404 {
        return Err("此账号尚无 Minecraft Java 版档案，请先在 minecraft.net 创建。".into());
    }
    let uuid = field(value, "id")
        .unwrap_or_default()
        .replace('-', "")
        .to_ascii_lowercase();
    let name = field(value, "name").unwrap_or_default();
    if status != 200
        || uuid.len() != 32
        || !uuid.bytes().all(|b| b.is_ascii_hexdigit())
        || name.len() > 16
        || name.is_empty()
        || !name.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_')
    {
        return Err("无法读取有效的 Minecraft Java 版档案。".into());
    }
    Ok(Account {
        uuid,
        name: name.into(),
        skin_url: value["skins"]
            .as_array()
            .and_then(|skins| {
                skins
                    .iter()
                    .find(|skin| field(skin, "state") == Some("ACTIVE"))
            })
            .and_then(|skin| field(skin, "url"))
            .filter(|url| url.len() <= 128)
            .map(str::to_owned),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn oauth_errors_and_browser_destinations_are_bounded() {
        assert!(
            oauth_error(&json!({"error":"unauthorized_client","error_description":"private"}))
                .contains("client ID")
        );
        assert_eq!(
            oauth_error(&json!({"error":"secret"})),
            "Microsoft sign-in failed."
        );
        assert_eq!(
            verification_uri(None).unwrap(),
            "https://www.microsoft.com/link"
        );
        assert!(verification_uri(Some("https://www.microsoft.com/link")).is_ok());
        assert!(verification_uri(Some("https://www.microsoft.com/user-supplied")).is_err());
        assert!(verification_uri(Some("https://microsoft.com.evil.test/devicelogin")).is_err());
        assert!(valid_client_id(CLIENT_ID));
        assert!(valid_client_id("00000000-0000-0000-0000-000000000000"));
        assert!(!valid_client_id("secret"));
        assert!(xsts_error(2148916233).contains("Xbox profile"));
        let mut interval = 5;
        assert!(poll_delay(
            &json!({"error":"authorization_pending"}),
            &mut interval
        ));
        assert_eq!(interval, 5);
        assert!(poll_delay(&json!({"error":"slow_down"}), &mut interval));
        assert_eq!(interval, 10);
        assert!(!poll_delay(
            &json!({"error":"authorization_declined"}),
            &mut interval
        ));
    }

    #[test]
    fn cancelled_device_flow_does_not_request_a_code() {
        assert_eq!(
            sign_in(
                "00000000-0000-0000-0000-000000000000",
                false,
                &AtomicBool::new(true),
                &|_| panic!("issued a code after cancellation"),
                &|_| {}
            )
            .err()
            .as_deref(),
            Some(CANCELLED)
        );
    }

    #[test]
    fn ownership_and_profile_fail_closed_and_session_has_no_refresh_token() {
        let entitlements = json!({"items":[{"name":"product_minecraft"}]});
        assert!(ownership(200, &entitlements).is_ok());
        assert!(ownership(503, &entitlements).is_err());
        assert!(ownership(200, &json!({"items":[]})).is_err());
        let profile = json!({"id":"069a79f4-44e9-4726-a5be-fca90e38aaf5","name":"Alex"});
        assert!(account(403, &profile).is_err());
        let mut s = Session {
            account: account(200, &profile).unwrap(),
            minecraft_token: "test-mc".into(),
            minecraft_expires_at: now() + 120,
            xuid: None,
        };
        assert!(s.usable());
        assert_eq!(
            serde_json::from_str::<Value>(&s.body()).unwrap(),
            json!({"name":"Alex","uuid":"069a79f444e94726a5befca90e38aaf5","access_token":"test-mc","user_type":"msa"})
        );
        s.minecraft_expires_at = now();
        assert!(!s.usable());
    }
}
