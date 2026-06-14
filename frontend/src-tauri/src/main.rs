use std::io::{BufRead, BufReader};
use std::net::TcpListener;
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread;
use std::time::Duration;

use tauri_plugin_shell::ShellExt;

struct AppState {
    api_url: String,
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
            api_url: api_url.clone(),
        })
        .setup(move |app| {
            // Try Tauri sidecar first, fall back to PATH binary
            let child_result = app.shell()
                .sidecar("cardre-api")
                .map(|cmd| cmd.args([port.to_string()]).spawn());

            match child_result {
                Ok(Ok(( mut rx, _child ))) => {
                    eprintln!("Started cardre-api via Tauri sidecar");
                    // Capture sidecar logs in background
                    thread::spawn(move || {
                        use tauri_plugin_shell::process::CommandEvent;
                        while let Some(event) = rx.recv() {
                            if let CommandEvent::Stdout(line) = event {
                                eprintln!("[sidecar] {}", String::from_utf8_lossy(&line).trim());
                            }
                            if let CommandEvent::Stderr(line) = event {
                                eprintln!("[sidecar:err] {}", String::from_utf8_lossy(&line).trim());
                            }
                        }
                    });
                }
                _ => {
                    // Fallback: try cardre-api from PATH (development mode)
                    eprintln!("Tauri sidecar binary not found; trying cardre-api from PATH");
                    match Command::new("cardre-api")
                        .arg(port.to_string())
                        .stdout(Stdio::piped())
                        .stderr(Stdio::piped())
                        .spawn()
                    {
                        Ok(mut child) => {
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
                            // Store child in app state for cleanup
                            // (simplified: process will be orphaned on exit)
                        }
                        Err(e) => {
                            eprintln!("FATAL: Could not start cardre-api: {}", e);
                            std::process::exit(1);
                        }
                    }
                }
            }

            match wait_for_health(port, 30) {
                Ok(()) => eprintln!("Sidecar is healthy on port {}", port),
                Err(e) => {
                    eprintln!("FATAL: {}", e);
                    std::process::exit(1);
                }
            }

            if let Some(window) = app.get_webview_window("main") {
                let _ = window.eval(&format!("window.__API_URL__ = '{}'", api_url));
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
