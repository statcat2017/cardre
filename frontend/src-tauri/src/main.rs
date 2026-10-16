#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::print_stderr,
    clippy::mutex_atomic,
    let_underscore_drop
)]

use std::net::TcpListener;
use std::process::Child;
use std::sync::Mutex;

use tauri::Manager;

mod sidecar;

use sidecar::{
    attach_log_readers, inject_api_url, inject_sidecar_error, kill_child, resolve_sidecar,
    spawn_sidecar, store_sidecar, wait_for_health,
};

struct AppState {
    sidecar_child: Mutex<Option<Child>>,
}

fn find_free_port() -> u16 {
    let listener = TcpListener::bind("127.0.0.1:0").expect("Failed to bind to ephemeral port");
    let port = listener.local_addr().unwrap().port();
    drop(listener);
    port
}

fn main() {
    let port = find_free_port();
    eprintln!("Reserved port: {port}");

    let api_url = format!("http://127.0.0.1:{port}");

    tauri::Builder::default()
        .manage(AppState {
            sidecar_child: Mutex::new(None),
        })
        .setup(move |app| -> Result<(), Box<dyn std::error::Error>> {
            let window = app
                .get_webview_window("main")
                .ok_or_else(|| -> Box<dyn std::error::Error> { "no main webview window".into() })?;

            let resource_dir = app.path().resource_dir().ok();
            let sidecar_result = (|| {
                let sidecar_path = resolve_sidecar(resource_dir.as_deref())?;
                eprintln!("sidecar: resolved path: {}", sidecar_path.display());
                eprintln!("sidecar: port: {port}");

                let mut child = spawn_sidecar(&sidecar_path, port)?;
                attach_log_readers(&mut child);

                if let Err(error) = wait_for_health(port, 30) {
                    kill_child(&mut child);
                    return Err(error);
                }
                eprintln!("sidecar: healthy on port {port}");

                let mut opt_child = Some(child);
                if let Err(error) = store_sidecar(app, &mut opt_child) {
                    if let Some(mut child) = opt_child {
                        kill_child(&mut child);
                    }
                    return Err(error);
                }
                Ok(())
            })();

            inject_api_url(&window, &api_url)
                .map_err(|error| -> Box<dyn std::error::Error> { error.into() })?;
            if let Err(error) = sidecar_result {
                eprintln!("sidecar: startup failed: {error}");
                inject_sidecar_error(&window, &error)
                    .map_err(|error| -> Box<dyn std::error::Error> { error.into() })?;
            }

            Ok(())
        })
        .on_window_event(|window, event| {
            if matches!(
                event,
                tauri::WindowEvent::CloseRequested { .. } | tauri::WindowEvent::Destroyed
            ) {
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
