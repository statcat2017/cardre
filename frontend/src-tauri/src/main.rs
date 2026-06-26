#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::print_stderr,
    clippy::mutex_atomic,
    clippy::let_with_underscore_drop
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
        .plugin(tauri_plugin_shell::init())
        .manage(AppState {
            sidecar_child: Mutex::new(None),
        })
        .setup(move |app| {
            // Find the sidecar binary
            let sidecar_cmd = if let Ok(path) = which::which("cardre-api") {
                path.to_string_lossy().to_string()
            } else {
                let bundled = app
                    .path()
                    .resource_dir()
                    .unwrap_or_default()
                    .join("binaries")
                    .join("cardre-api");
                if bundled.exists() {
                    bundled.to_string_lossy().to_string()
                } else {
                    "cardre-api".to_string()
                }
            };

            let mut child: Child = match Command::new(&sidecar_cmd)
                .arg(port.to_string())
                .stdout(Stdio::piped())
                .stderr(Stdio::piped())
                .spawn()
            {
                Ok(c) => {
                    eprintln!("Started cardre-api sidecar");
                    c
                }
                Err(e) => {
                    eprintln!("FATAL: Could not start cardre-api: {e}");
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
                Ok(()) => eprintln!("Sidecar is healthy on port {port}"),
                Err(e) => {
                    eprintln!("FATAL: {e}");
                    if let Ok(mut guard) = app.state::<AppState>().sidecar_child.lock() {
                        if let Some(ref mut c) = *guard {
                            kill_child(c);
                        }
                    }
                    std::process::exit(1);
                }
            }

            if let Some(window) = app.get_webview_window("main") {
                let _ = window.eval(&format!("window.__API_URL__ = '{api_url}'"));
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
