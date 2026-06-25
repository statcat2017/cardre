# Security Policy

## Data Handling

Cardre is a local-first application. All data stays on your machine:

- **SQLite databases** are stored in your project directory.
- **Parquet/JSON artifacts** are stored in your project directory.
- **No telemetry**: Cardre does not phone home, collect usage data, or send any information over the network.
- **No cloud dependencies**: The sidecar API runs locally. There is no cloud backend.

## Reporting a Vulnerability

If you discover a security vulnerability, please open an issue with the "security" label or contact the maintainers directly. Do not disclose security vulnerabilities publicly until they have been addressed.

## Supported Versions

| Version | Supported |
|---------|-----------|
| latest release | ✅ |
| development branch | ⚠️ (best effort) |
| older releases | ❌ |

## Security Best Practices

- Run Cardre in an isolated environment when processing sensitive data.
- Review the audit trail (run manifests, step evidence) before relying on model outputs for regulated decisions.
- Keep dependencies up to date via `pip install --upgrade cardre`.
