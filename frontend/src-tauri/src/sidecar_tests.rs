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

#[cfg(target_os = "linux")]
#[test]
fn resolve_sidecar_uses_debian_sibling_binary_when_present() {
    let tmp = tempfile::tempdir().expect("tempdir");
    let bin_dir = tmp.path().join("usr/bin");
    std::fs::create_dir_all(&bin_dir).unwrap();
    let app_path = bin_dir.join("cardre");
    let sidecar_path = installed_sidecar_path(&app_path);
    std::fs::write(&sidecar_path, b"sidecar").unwrap();

    let resolved = resolve_sidecar_from(None, Some(&app_path)).expect("installed sidecar");
    assert_eq!(resolved, sidecar_path);
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

#[test]
fn api_url_assignment_uses_the_selected_loopback_port() {
    let script = api_url_assignment_script("http://127.0.0.1:43129").unwrap();
    assert!(script.contains("http://127.0.0.1:43129"));
    assert!(!script.contains("8752"));
}

#[test]
fn sidecar_startup_error_is_serialized_as_javascript_data() {
    let script =
        sidecar_error_assignment_script("missing sidecar: \"cardre-api\"").expect("script");
    assert_eq!(
        script,
        r#"window.__SIDECAR_STARTUP_ERROR__ = "missing sidecar: \"cardre-api\"""#
    );
}

#[test]
fn sidecar_cors_origins_include_tauri_and_preserve_configured_origins() {
    assert_eq!(
        sidecar_cors_origins(Some("https://example.test, tauri://localhost")),
        "tauri://localhost,https://example.test"
    );
    assert_eq!(
            sidecar_cors_origins(None),
            "tauri://localhost,http://localhost:1420,http://localhost:5173,http://127.0.0.1:1420,http://127.0.0.1:5173"
        );
}
