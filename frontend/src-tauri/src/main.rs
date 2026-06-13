use std::io::{BufRead, BufReader};
use std::net::TcpListener;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

struct AppState {
    child: Mutex<Option<Child>>,
    api_url: String,
}

fn find_free_port() -> u16 {
    let listener = TcpListener::bind("127.0.0.1:0").expect("Failed to bind to ephemeral port");
    let port = listener.local_addr().unwrap().port();
    drop(listener);
    port
}

fn start_sidecar(port: u16) -> Child {
    Command::new("cardre-api")
        .arg(port.to_string())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("Failed to start cardre-api sidecar")
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

    let mut child = start_sidecar(port);

    // Take stdout/stderr ownership cleanly to avoid borrow issues
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

    match wait_for_health(port, 30) {
        Ok(()) => eprintln!("Sidecar is healthy on port {}", port),
        Err(e) => {
            eprintln!("FATAL: {}", e);
            let _ = child.kill();
            std::process::exit(1);
        }
    }

    let api_url = format!("http://127.0.0.1:{}", port);

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(AppState {
            child: Mutex::new(Some(child)),
            api_url: api_url.clone(),
        })
        .setup(|app| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.eval(&format!("window.__API_URL__ = '{}'", api_url));
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                if let Some(state) = window.try_state::<AppState>() {
                    if let Ok(mut child_opt) = state.child.lock() {
                        if let Some(ref mut child) = *child_opt {
                            let _ = child.kill();
                            let _ = child.wait();
                        }
                        *child_opt = None;
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
