use std::process::Command;

#[test]
fn no_arguments_start_offline() {
    let result = Command::new(env!("CARGO_BIN_EXE_mc-login"))
        .env_remove("HORIZON_MSA_CLIENT_ID")
        .env_remove("LOCALAPPDATA")
        .output()
        .unwrap();
    assert_eq!(result.status.code(), Some(1));
    let stderr = String::from_utf8_lossy(&result.stderr);
    assert!(
        stderr.contains("LOCALAPPDATA is not set") || stderr.contains("Horizon checkout not found")
    );
}

#[test]
fn login_rejects_invalid_developer_override() {
    let result = Command::new(env!("CARGO_BIN_EXE_mc-login"))
        .args(["login", "--client-id", "not-a-guid"])
        .output()
        .unwrap();
    assert_eq!(result.status.code(), Some(2));
    assert!(String::from_utf8_lossy(&result.stderr).contains("client) ID in GUID format"));
}

#[test]
fn play_does_not_require_a_client_id() {
    let missing = std::env::temp_dir().join(format!("mc-login-no-horizon-{}", std::process::id()));
    let result = Command::new(env!("CARGO_BIN_EXE_mc-login"))
        .args(["play", "--horizon-dir"])
        .arg(missing)
        .env_remove("HORIZON_MSA_CLIENT_ID")
        .env("LOCALAPPDATA", std::env::temp_dir())
        .output()
        .unwrap();
    assert!(!result.status.success());
    assert!(String::from_utf8_lossy(&result.stderr).contains("local Horizon client not found"));
}

#[test]
fn play_rejects_online_session_flags() {
    let result = Command::new(env!("CARGO_BIN_EXE_mc-login"))
        .args(["play", "--session-stdin"])
        .output()
        .unwrap();
    assert!(!result.status.success());
    assert!(String::from_utf8_lossy(&result.stderr).contains("unknown play option --session-stdin"));
}
