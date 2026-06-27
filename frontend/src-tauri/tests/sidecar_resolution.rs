//! Integration test: bundled sidecar naming contract.
//!
//! Asserts that tauri.conf.json, build-sidecar.sh, and main.rs agree on the
//! sidecar name. Does NOT depend on TAURI_ENV_TARGET_TRIPLE (not available in
//! integration test binaries). The triple-dependent unit tests live in main.rs.
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
}

#[test]
fn main_rs_defines_sidecar_name_constant() {
    let main_rs = include_str!("../src/main.rs");
    assert!(
        main_rs.contains("SIDECAR_NAME: &str = \"cardre-api\""),
        "main.rs must define SIDECAR_NAME = cardre-api"
    );
    assert!(
        main_rs.contains("TAURI_ENV_TARGET_TRIPLE"),
        "main.rs must use TAURI_ENV_TARGET_TRIPLE"
    );
    assert!(
        main_rs.contains("sidecar_binary_name()"),
        "main.rs must use sidecar_binary_name()"
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
