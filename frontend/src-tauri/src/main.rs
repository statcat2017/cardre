#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::print_stderr,
    clippy::mutex_atomic,
    let_underscore_drop
)]

use std::io::{BufRead, BufReader, Read};
use std::net::TcpListener;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

use tauri::Manager;

struct AppState {
    sidecar_child: Mutex<Option<Child>>,
}

fn find_free_port() -> u16 {
    let listener = TcpListener::bind("127.0.0.1:0").expect("Failed to bind to ephemeral port");
    let port = listener.local_addr().unwrap().port();
    // Drop the listener immediately. This creates a brief TOCTOU window
    // where another process could bind the port before the sidecar starts.
    // A production fix would pass the listener fd directly, but that
    // requires platform-specific code.
    drop(listener);
    port
}

fn wait_for_health(port: u16, max_retries: u32) -> Result<(), String> {
    let url = format!("http://127.0.0.1:{port}/health");
    for _ in 0..max_retries {
        let healthy = reqwest::blocking::get(&url)
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
        // Responded but not healthy yet — retry
        thread::sleep(Duration::from_millis(500));
    }
    Err(format!(
        "Sidecar did not become healthy within {} seconds",
        max_retries * 500 / 1000
    ))
}

fn kill_child(child: &mut Child) {
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

/// Resolve the sidecar binary path. Bundled first; dev PATH fallback second.
/// Returns Err with both attempted paths so the failure is diagnosable.
fn resolve_sidecar(resource_dir: Option<&std::path::Path>) -> Result<std::path::PathBuf, String> {
    if let Some(rd) = resource_dir {
        let bundled = bundled_sidecar_path(rd);
        if bundled.exists() {
            return Ok(bundled);
        }
        eprintln!("sidecar: bundled path not found: {}", bundled.display());
    }

    // Dev-only fallback: cardre-api on PATH (pip install -e ".[sidecar]").
    // In release builds (packaged app), fail hard if the bundled binary is missing.
    #[cfg(debug_assertions)]
    if let Ok(p) = which::which(SIDECAR_NAME) {
        eprintln!("sidecar: dev fallback using PATH entry: {}", p.display());
        return Ok(p);
    }

    Err(format!(
        "Could not resolve sidecar. Bundled: {:?}; PATH entry `{SIDECAR_NAME}` not found.",
        resource_dir.map(bundled_sidecar_path)
    ))
}

fn main() {
    let running = Arc::new(AtomicBool::new(true));
    let r = running.clone();

    ctrlc::set_handler(move || {
        r.store(false, Ordering::SeqCst);
    })
    .expect("Error setting Ctrl-C handler");

    let port = find_free_port();
    eprintln!("Reserved port: {port}");

    let api_url = format!("http://127.0.0.1:{port}");

    tauri::Builder::default()
        .manage(AppState {
            sidecar_child: Mutex::new(None),
        })
        .setup(move |app| {
            // Resolve the sidecar binary: bundled first (packaged), then dev PATH fallback.
            let resource_dir = app.path().resource_dir().ok();
            let sidecar_path = match resolve_sidecar(resource_dir.as_deref()) {
                Ok(p) => p,
                Err(e) => {
                    eprintln!("FATAL: {e}");
                    std::process::exit(1);
                }
            };
            eprintln!("sidecar: resolved path: {}", sidecar_path.display());
            eprintln!("sidecar: port: {port}");

            let mut child: Child = match Command::new(&sidecar_path)
                .arg(port.to_string())
                .stdout(Stdio::piped())
                .stderr(Stdio::piped())
                .spawn()
            {
                Ok(c) => {
                    eprintln!(
                        "sidecar: started {} (pid {})",
                        sidecar_path.display(),
                        c.id()
                    );
                    c
                }
                Err(e) => {
                    eprintln!(
                        "FATAL: Could not start sidecar at {}: {e}",
                        sidecar_path.display()
                    );
                    std::process::exit(1);
                }
            };

            // Capture stdout
            if let Some(stdout) = child.stdout.take() {
                spawn_line_reader(stdout, "[sidecar] ");
            }

            // Capture stderr
            if let Some(stderr) = child.stderr.take() {
                spawn_line_reader(stderr, "[sidecar:err] ");
            }

            // Store child handle for lifecycle management
            if let Ok(mut guard) = app.state::<AppState>().sidecar_child.lock() {
                *guard = Some(child);
            }

            // Wait for health before declaring setup complete.
            // The Child handle remains in AppState for cleanup.
            match wait_for_health(port, 30) {
                Ok(()) => eprintln!("sidecar: healthy on port {port}"),
                Err(e) => {
                    eprintln!(
                        "FATAL: sidecar health check failed: {e} (path={}, port={port})",
                        sidecar_path.display()
                    );
                    if let Ok(mut guard) = app.state::<AppState>().sidecar_child.lock() {
                        if let Some(ref mut c) = *guard {
                            kill_child(c);
                        }
                    }
                    std::process::exit(1);
                }
            }

            if let Some(window) = app.get_webview_window("main") {
                let _ = window.eval(format!("window.__API_URL__ = '{api_url}'").as_str());
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                if let Ok(mut guard) = window.state::<AppState>().sidecar_child.lock() {
                    if let Some(ref mut c) = *guard {
                        kill_child(c);
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resolve_sidecar_prefers_bundled_when_present() {
        let tmp = tempfile::tempdir().expect("tempdir");
        let resource = tmp.path();
        let bin_dir = resource.join("binaries");
        std::fs::create_dir_all(&bin_dir).unwrap();
        let bin_path = bin_dir.join(sidecar_binary_name());
        std::fs::write(&bin_path, b"#!fake\n").unwrap();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&bin_path, std::fs::Permissions::from_mode(0o755)).unwrap();
        }

        let resolved = resolve_sidecar(Some(resource)).expect("should resolve");
        assert_eq!(resolved, bin_path);
    }

    #[test]
    fn resolve_sidecar_errors_when_bundled_absent_and_not_on_path() {
        let tmp = tempfile::tempdir().expect("tempdir");
        let err = resolve_sidecar(Some(tmp.path())).unwrap_err();
        assert!(
            err.contains("binaries/cardre-api-"),
            "err should list bundled path: {err}"
        );
        assert!(
            err.contains(SIDECAR_NAME),
            "err should mention PATH entry: {err}"
        );
    }

    #[test]
    fn bundled_sidecar_path_uses_binaries_subdir_and_triple_name() {
        let dir = std::path::PathBuf::from("/tmp/fake-resource");
        let path = bundled_sidecar_path(&dir);
        assert_eq!(path, dir.join("binaries").join(sidecar_binary_name()));
        assert!(path.to_string_lossy().contains("binaries/cardre-api-"));
    }

    #[test]
    fn sidecar_binary_name_includes_target_triple() {
        let name = sidecar_binary_name();
        assert!(
            name.starts_with("cardre-api-"),
            "expected cardre-api-{{triple}}, got {name}"
        );
        assert!(
            !name.ends_with(".exe") || cfg!(windows),
            ".exe suffix must only appear on windows, got {name}"
        );
        if cfg!(windows) {
            assert!(
                name.ends_with(".exe"),
                "windows name must end .exe, got {name}"
            );
        }
    }
}
