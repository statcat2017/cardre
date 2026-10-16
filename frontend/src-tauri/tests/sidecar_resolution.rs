//! Integration test: bundled sidecar naming contract.
//!
//! Asserts that tauri.conf.json, build-sidecar.sh, and sidecar.rs agree on the
//! sidecar name. Does NOT depend on TAURI_ENV_TARGET_TRIPLE (not available in
//! integration test binaries). The triple-dependent unit tests live in sidecar.rs.
//!
//! Run: cargo test --test sidecar_resolution

const SIDECAR_STEM: &str = "binaries/cardre-api";

#[test]
fn stem_in_tauri_conf_is_cardre_api() {
    let conf = include_str!("../tauri.conf.json");
    assert!(
        conf.contains("\"externalBin\""),
        "tauri.conf.json must declare externalBin"
    );
    assert!(
        conf.contains(SIDECAR_STEM),
        "tauri.conf.json externalBin must list {SIDECAR_STEM}"
    );
}

#[test]
fn build_sidecar_script_produces_triple_suffixed_name() {
    let script = include_str!("../../../scripts/build-sidecar.sh");
    assert!(
        script.contains("--name cardre-api"),
        "build-sidecar.sh must pyinstaller --name cardre-api"
    );
    assert!(
        script.contains("cardre-api-${TARGET}"),
        "build-sidecar.sh must rename to cardre-api-${{TARGET}}"
    );
    assert!(
        script.contains("--paths \"$REPO_DIR\""),
        "build-sidecar.sh must add repo root to PyInstaller paths"
    );
}

#[test]
fn main_rs_uses_sidecar_module_and_sidecar_rs_defines_name() {
    let main_rs = include_str!("../src/main.rs");
    let sidecar_rs = include_str!("../src/sidecar.rs");
    assert!(
        main_rs.contains("mod sidecar;"),
        "main.rs must load the sidecar module"
    );
    assert!(
        sidecar_rs.contains("SIDECAR_NAME: &str = \"cardre-api\""),
        "sidecar.rs must define SIDECAR_NAME = cardre-api"
    );
    assert!(
        sidecar_rs.contains("TAURI_ENV_TARGET_TRIPLE"),
        "sidecar.rs must use TAURI_ENV_TARGET_TRIPLE"
    );
    assert!(
        sidecar_rs.contains("sidecar_binary_name()"),
        "sidecar.rs must use sidecar_binary_name()"
    );
    assert!(
        main_rs.contains("resolve_sidecar"),
        "main.rs must use resolve_sidecar()"
    );
}

#[test]
fn binaries_dir_contains_expected_file_when_built() {
    let bin_dir = std::path::Path::new("binaries");
    if !bin_dir.exists() {
        // Developer-friendly: locally we may not have built the sidecar. But in
        // CI the sidecar artifact is downloaded before this test runs, so a
        // missing binaries/ dir there is a real failure.
        if std::env::var_os("CARDRE_CI_REQUIRE_BINARIES").is_some() {
            panic!(
                "binaries/ directory not found: expected the packaged sidecar \
                 artifact to be present (CARDRE_CI_REQUIRE_BINARIES set). \
                 Ensure the build-sidecar artifact is downloaded before the test."
            );
        }
        eprintln!("skipped: binaries/ not present (no sidecar built in this env)");
        return;
    }
    let entries: Vec<_> = std::fs::read_dir(bin_dir)
        .unwrap()
        .filter_map(|e| e.ok())
        .map(|e| e.file_name().to_string_lossy().to_string())
        .collect();
    assert!(
        entries.iter().any(|n| n.starts_with("cardre-api-")),
        "expected a cardre-api-* file in binaries/, got: {:?}",
        entries
    );
}
