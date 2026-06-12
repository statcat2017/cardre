use std::net::TcpListener;
use std::sync::Mutex;
use std::time::Duration;

use tauri::Manager;

struct AppState {
    api_url: String,
}

fn reserve_port() -> u16 {
    let listener = TcpListener::bind("127.0.0.1:0").expect("Failed to bind to ephemeral port");
    let port = listener.local_addr().unwrap().port();
    drop(listener);
    port
}

fn wait_for_health(port: u16) {
    let url = format!("http://127.0.0.1:{}/health", port);
    for _ in 0..30 {
        if reqwest::blocking::get(&url).is_ok() {
            return;
        }
        std::thread::sleep(Duration::from_millis(500));
    }
    panic!("Sidecar did not become healthy within 15 seconds");
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            let port = reserve_port();
            println!("Reserved port: {}", port);

            let (mut rx, _child) = app
                .shell()
                .sidecar("cardre-api")
                .expect("failed to create sidecar command")
                .args([port.to_string()])
                .spawn()
                .expect("failed to spawn sidecar");

            wait_for_health(port);
            println!("Sidecar is healthy on port {}", port);

            let api_url = format!("http://127.0.0.1:{}", port);
            app.manage(AppState {
                api_url: api_url.clone(),
            });

            // Expose the API URL to the frontend
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.eval(&format!(
                    "window.__API_URL__ = '{}'",
                    api_url
                ));
            }

            // Spawn log capture
            std::thread::spawn(move || {
                while let Some(event) = rx.blocking_recv() {
                    match event {
                        tauri_plugin_shell::process::CommandEvent::Stdout(line) => {
                            println!("[sidecar] {}", String::from_utf8_lossy(&line));
                        }
                        tauri_plugin_shell::process::CommandEvent::Stderr(line) => {
                            eprintln!("[sidecar:err] {}", String::from_utf8_lossy(&line));
                        }
                        _ => {}
                    }
                }
            });

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
