use std::io::{BufRead, BufReader};
use std::net::TcpListener;
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

use tauri::Manager;

struct AppState {
    sidecar_pid: Mutex<Option<u32>>,
}

fn find_free_port() -> u16 {
    let listener = TcpListener::bind("127.0.0.1:0").expect("Failed to bind to ephemeral port");
    let port = listener.local_addr().unwrap().port();
    drop(listener);
    port
}

fn wait_for_health(port: u16, max_retries: u32) -> Result<(), String> {
    let url = format!("http://127.0.0.1:{}/health", port);
    for _ in 0..max_retries {
        if reqwest::blocking::get(&url).is_ok() {
            return Ok(());
        }
        thread::sleep(Duration::from_millis(500));
    }
    Err(format!(
        "Sidecar did not become healthy within {} seconds",
        max_retries * 500 / 1000
    ))
}

fn kill_process(pid: u32) {
    // Send SIGTERM on Unix, TerminateProcess on Windows
    #[cfg(unix)]
    {
        let _ = Command::new("kill")
            .arg(pid.to_string())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
    }
    #[cfg(windows)]
    {
        let _ = Command::new("taskkill")
            .args(["/F", "/PID", &pid.to_string()])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
    }
}

fn main() {
    let running = Arc::new(AtomicBool::new(true));
    let r = running.clone();

    ctrlc::set_handler(move || {
        r.store(false, Ordering::SeqCst);
    })
    .expect("Error setting Ctrl-C handler");

    let port = find_free_port();
    eprintln!("Reserved port: {}", port);

    let api_url = format!("http://127.0.0.1:{}", port);

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(AppState {
            sidecar_pid: Mutex::new(None),
        })
        .setup(move |app| {
            let mut child: std::process::Child = match Command::new("cardre-api")
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
                    eprintln!("FATAL: Could not start cardre-api: {}", e);
                    std::process::exit(1);
                }
            };

            let child_pid = child.id();

            // Capture stdout
            if let Some(stdout) = child.stdout.take() {
                let reader = BufReader::new(stdout);
                thread::spawn(move || {
                    for line in reader.lines() {
                        if let Ok(l) = line {
                            eprintln!("[sidecar] {}", l);
                        }
                    }
                });
            }

            // Capture stderr
            if let Some(stderr) = child.stderr.take() {
                let reader = BufReader::new(stderr);
                thread::spawn(move || {
                    for line in reader.lines() {
                        if let Ok(l) = line {
                            eprintln!("[sidecar:err] {}", l);
                        }
                    }
                });
            }

            // Store PID for cleanup — the Child handle is detached
            // (std::process::Child::drop does not kill the process).
            if let Ok(mut guard) = app.state::<AppState>().sidecar_pid.lock() {
                *guard = Some(child_pid);
            }

            drop(child);

            match wait_for_health(port, 30) {
                Ok(()) => eprintln!("Sidecar is healthy on port {}", port),
                Err(e) => {
                    eprintln!("FATAL: {}", e);
                    kill_process(child_pid);
                    std::process::exit(1);
                }
            }

            if let Some(window) = app.get_webview_window("main") {
                let _ = window.eval(&format!("window.__API_URL__ = '{}'", api_url));
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                if let Ok(mut guard) = window.state::<AppState>().sidecar_pid.lock() {
                    if let Some(pid) = guard.take() {
                        kill_process(pid);
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
