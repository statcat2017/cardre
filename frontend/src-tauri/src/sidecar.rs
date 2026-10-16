use std::io::{BufRead, BufReader, Read};
use std::process::{Child, Command, Stdio};
use std::thread;
use std::time::Duration;

use tauri::Manager;

pub(crate) fn wait_for_health(port: u16, max_retries: u32) -> Result<(), String> {
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .map_err(|e| format!("Failed to build HTTP client: {e}"))?;
    let url = format!("http://127.0.0.1:{port}/health");
    for _ in 0..max_retries {
        let healthy = client
            .get(&url)
            .send()
            .ok()
            .and_then(|resp| resp.json::<serde_json::Value>().ok())
            .and_then(|body| {
                if body.get("status").and_then(|v| v.as_str()) == Some("ok") {
                    Some(())
                } else {
                    None
                }
            })
            .is_some();
        if healthy {
            return Ok(());
        }
        thread::sleep(Duration::from_millis(500));
    }
    Err(format!(
        "Sidecar did not become healthy within {} seconds",
        max_retries * 500 / 1000
    ))
}

pub(crate) fn kill_child(child: &mut Child) {
    #[cfg(unix)]
    {
        let process_group = -(child.id() as libc::pid_t);
        // SAFETY: spawn_sidecar puts this child in a process group led by its PID.
        // Signaling that group stops PyInstaller's worker process as well as its launcher.
        let _ = unsafe { libc::kill(process_group, libc::SIGKILL) };
    }
    let _ = child.kill();
    let _ = child.wait();
}

fn spawn_line_reader<T: Read + Send + 'static>(stream: T, prefix: &str) {
    let reader = BufReader::new(stream);
    let prefix = prefix.to_string();
    thread::spawn(move || {
        for l in reader.lines().map_while(Result::ok) {
            eprintln!("{prefix}{l}");
        }
    });
}

const SIDECAR_NAME: &str = "cardre-api";

/// The target triple embedded at compile time by tauri-build.
fn target_triple() -> &'static str {
    env!("TAURI_ENV_TARGET_TRIPLE")
}

/// Bundled sidecar filename: `cardre-api-{triple}` plus `.exe` on Windows.
fn sidecar_binary_name() -> String {
    let base = format!("{SIDECAR_NAME}-{}", target_triple());
    if cfg!(windows) {
        format!("{base}.exe")
    } else {
        base
    }
}

/// Path to the bundled sidecar inside a Tauri resource dir.
fn bundled_sidecar_path(resource_dir: &std::path::Path) -> std::path::PathBuf {
    resource_dir.join("binaries").join(sidecar_binary_name())
}

#[cfg(target_os = "linux")]
fn installed_sidecar_path(app_executable: &std::path::Path) -> std::path::PathBuf {
    app_executable
        .parent()
        .unwrap_or_else(|| std::path::Path::new(""))
        .join(SIDECAR_NAME)
}

/// Resolve the sidecar binary from Tauri resources, the Linux package layout, or dev PATH.
pub(crate) fn resolve_sidecar(
    resource_dir: Option<&std::path::Path>,
) -> Result<std::path::PathBuf, String> {
    resolve_sidecar_from(resource_dir, std::env::current_exe().ok().as_deref())
}

fn resolve_sidecar_from(
    resource_dir: Option<&std::path::Path>,
    app_executable: Option<&std::path::Path>,
) -> Result<std::path::PathBuf, String> {
    if let Some(rd) = resource_dir {
        let bundled = bundled_sidecar_path(rd);
        if bundled.exists() {
            return Ok(bundled);
        }
        eprintln!("sidecar: bundled path not found: {}", bundled.display());
    }

    #[cfg(target_os = "linux")]
    if let Some(app_executable) = app_executable {
        let installed = installed_sidecar_path(app_executable);
        if installed.exists() {
            return Ok(installed);
        }
        eprintln!("sidecar: installed path not found: {}", installed.display());
    }

    #[cfg(debug_assertions)]
    if let Ok(p) = which::which(SIDECAR_NAME) {
        eprintln!("sidecar: dev fallback using PATH entry: {}", p.display());
        return Ok(p);
    }

    #[cfg(target_os = "linux")]
    let installed_path = app_executable.map(installed_sidecar_path);
    #[cfg(not(target_os = "linux"))]
    let installed_path: Option<std::path::PathBuf> = None;

    Err(format!(
        "Could not resolve sidecar. Bundled: {:?}; installed beside app: {:?}; PATH entry `{SIDECAR_NAME}` not found.",
        resource_dir.map(bundled_sidecar_path),
        installed_path
    ))
}

fn api_url_assignment_script(api_url: &str) -> Result<String, String> {
    let url_str =
        serde_json::to_string(api_url).map_err(|e| format!("URL serialization failed: {e}"))?;
    Ok(format!("window.__API_URL__ = {url_str}"))
}

fn sidecar_error_assignment_script(error: &str) -> Result<String, String> {
    let error_str =
        serde_json::to_string(error).map_err(|e| format!("Error serialization failed: {e}"))?;
    Ok(format!("window.__SIDECAR_STARTUP_ERROR__ = {error_str}"))
}

fn sidecar_cors_origins(configured: Option<&str>) -> String {
    const DEFAULT_ORIGINS: &str =
        "http://localhost:1420,http://localhost:5173,http://127.0.0.1:1420,http://127.0.0.1:5173";
    let configured = configured
        .filter(|origins| !origins.trim().is_empty())
        .unwrap_or(DEFAULT_ORIGINS);
    let mut origins = vec!["tauri://localhost"];
    for origin in configured
        .split(',')
        .map(str::trim)
        .filter(|value| !value.is_empty())
    {
        if !origins.contains(&origin) {
            origins.push(origin);
        }
    }
    origins.join(",")
}

pub(crate) fn inject_api_url(window: &tauri::WebviewWindow, api_url: &str) -> Result<(), String> {
    let script = api_url_assignment_script(api_url)?;
    window
        .eval(&script)
        .map_err(|e| format!("failed to inject API URL: {e}"))
}

pub(crate) fn inject_sidecar_error(
    window: &tauri::WebviewWindow,
    error: &str,
) -> Result<(), String> {
    let script = sidecar_error_assignment_script(error)?;
    window
        .eval(&script)
        .map_err(|e| format!("failed to inject sidecar startup error: {e}"))
}

pub(crate) fn store_sidecar(app: &tauri::App, child: &mut Option<Child>) -> Result<(), String> {
    let state = app.state::<crate::AppState>();
    let mut guard = state
        .sidecar_child
        .lock()
        .map_err(|_| "sidecar state lock poisoned".to_owned())?;
    let taken = child
        .take()
        .ok_or_else(|| "sidecar child already taken".to_owned())?;
    *guard = Some(taken);
    Ok(())
}

pub(crate) fn spawn_sidecar(sidecar_path: &std::path::Path, port: u16) -> Result<Child, String> {
    let cors_origins = sidecar_cors_origins(std::env::var("CARDRE_CORS_ORIGINS").ok().as_deref());
    let mut command = Command::new(sidecar_path);
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        command.process_group(0);
    }

    let child = command
        .env("CARDRE_API_PORT", port.to_string())
        .env("CARDRE_API_HOST", "127.0.0.1")
        .env("CARDRE_CORS_ORIGINS", cors_origins)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("Could not start sidecar at {}: {e}", sidecar_path.display()))?;
    eprintln!(
        "sidecar: started {} (pid {})",
        sidecar_path.display(),
        child.id()
    );
    Ok(child)
}

pub(crate) fn attach_log_readers(child: &mut Child) {
    if let Some(stdout) = child.stdout.take() {
        spawn_line_reader(stdout, "[sidecar] ");
    }
    if let Some(stderr) = child.stderr.take() {
        spawn_line_reader(stderr, "[sidecar:err] ");
    }
}

#[cfg(test)]
#[path = "sidecar_tests.rs"]
mod tests;
