use std::io::{BufRead, BufReader};
use std::net::TcpListener;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

use tauri_plugin_shell::ShellExt;

struct AppState {
    sidecar_pid: Mutex<Option<u32>>,
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
            api_url: api_url.clone(),
        })
        .setup(move |app| {
            let pid: Option<u32>;

            // Try Tauri sidecar first
            match app.shell().sidecar("cardre-api") {
                Ok(cmd) => match cmd.args([port.to_string()]).spawn() {
                    Ok((mut rx, tauri_child)) => {
                        eprintln!("Started cardre-api via Tauri sidecar");
                        pid = Some(tauri_child.pid());
                        // Capture sidecar logs in background
                        thread::spawn(move || {
                            while let Some(event) = rx.recv() {
                                match event {
                                    tauri_plugin_shell::process::CommandEvent::Stdout(line) => {
                                        eprintln!("[sidecar] {}", String::from_utf8_lossy(&line).trim());
                                    }
                                    tauri_plugin_shell::process::CommandEvent::Stderr(line) => {
                                        eprintln!("[sidecar:err] {}", String::from_utf8_lossy(&line).trim());
                                    }
                                    _ => {}
                                }
                            }
                        });
                    }
                    Err(e) => {
                        eprintln!("Tauri sidecar spawn failed: {}; trying PATH fallback", e);
                        pid = None;
                    }
                },
                Err(e) => {
                    eprintln!("Tauri sidecar binary not found: {}; trying PATH fallback", e);
                    pid = None;
                }
            }

            // Fallback: cardre-api from PATH
            let pid = match pid {
                Some(p) => Some(p),
                None => {
                    match Command::new("cardre-api")
                        .arg(port.to_string())
                        .stdout(Stdio::piped())
                        .stderr(Stdio::piped())
                        .spawn()
                    {
                        Ok(mut fallback_child) => {
                            eprintln!("Started cardre-api via PATH fallback");
                            let child_pid = fallback_child.id();
                            if let Some(stdout) = fallback_child.stdout.take() {
                                let reader = BufReader::new(stdout);
                                thread::spawn(move || {
                                    for line in reader.lines() {
                                        if let Ok(l) = line {
                                            eprintln!("[sidecar] {}", l);
                                        }
                                    }
                                });
                            }
                            if let Some(stderr) = fallback_child.stderr.take() {
                                let reader = BufReader::new(stderr);
                                thread::spawn(move || {
                                    for line in reader.lines() {
                                        if let Ok(l) = line {
                                            eprintln!("[sidecar:err] {}", l);
                                        }
                                    }
                                });
                            }
                            // Detach the child handle — the process lives on.
                            // We track it by PID for cleanup.
                            Some(child_pid)
                        }
                        Err(e) => {
                            eprintln!("FATAL: Could not start cardre-api: {}", e);
                            std::process::exit(1);
                        }
                    }
                }
            };

            // Store PID for cleanup
            if let Some(state) = app.try_state::<AppState>() {
                if let Ok(mut guard) = state.sidecar_pid.lock() {
                    *guard = pid;
                }
            }

            match wait_for_health(port, 30) {
                Ok(()) => eprintln!("Sidecar is healthy on port {}", port),
                Err(e) => {
                    eprintln!("FATAL: {}", e);
                    if let Some(p) = pid {
                        kill_process(p);
                    }
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
                if let Some(state) = window.try_state::<AppState>() {
                    if let Ok(mut guard) = state.sidecar_pid.lock() {
                        if let Some(pid) = guard.take() {
                            kill_process(pid);
                        }
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
