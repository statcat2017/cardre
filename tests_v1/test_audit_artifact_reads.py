from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_module():
    script_path = REPO_ROOT / "scripts" / "audit_artifact_reads.py"
    spec = importlib.util.spec_from_file_location("audit_artifact_reads", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(path: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=path, check=True, capture_output=True, text=True)


def _write(path: Path, rel: str, content: str) -> None:
    target = path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def test_audit_artifact_reads_smoke_scan(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")

    _write(
        repo,
        "cardre/prod_reader.py",
        "from pathlib import Path\n"
        "import json\n"
        "def read(store, art):\n"
        "    return json.loads(store.artifact_path(art).read_text())\n",
    )
    _write(
        repo,
        "cardre/alias_reader.py",
        "import json\n"
        "def read(store, art):\n"
        "    path = store.artifact_path(art)\n"
        "    return json.loads(path.read_text())\n",
    )
    _write(
        repo,
        "cardre/_evidence/reader.py",
        "import polars as pl\n"
        "def read(store, art):\n"
        "    return pl.scan_parquet(store.artifact_path(art)).collect_schema()\n",
    )
    _write(
        repo,
        "cardre/artifacts.py",
        "import json\n"
        "def low_level(store, art):\n"
        "    return json.loads(store.artifact_path(art).read_text())\n",
    )
    _write(
        repo,
        "cardre/modeling/serialization.py",
        "def load(store, art):\n"
        "    with open(store.artifact_path(art), 'rb') as handle:\n"
        "        return handle.read()\n",
    )
    _write(
        repo,
        "cardre/custom_io.py",
        "import json\n"
        "def read(store, art):\n"
        "    return json.loads(store.artifact_path(art).read_text())\n",
    )
    _write(
        repo,
        "cardre/suppressed.py",
        "def read(store, art):\n"
        "    return open(store.artifact_path(art))  # cardre-allow-artifact-read: artifact-byte-download\n",
    )
    _write(
        repo,
        "cardre/invalid_suppression.py",
        "def read(store, art):\n"
        "    return open(store.artifact_path(art))  # cardre-allow-artifact-read: nope\n",
    )
    _write(
        repo,
        "tests/test_reader.py",
        "import polars as pl\n"
        "def test_read(store, art):\n"
        "    return pl.read_parquet(store.artifact_path(art))\n",
    )
    _write(
        repo,
        "docs/reference.py",
        "def docs(store, art):\n"
        "    return open(store.artifact_path(art))\n",
    )
    _write(
        repo,
        "tests/test_docstring_scan.py",
        '"""Example: json.loads(store.artifact_path(art).read_text()) should not be scanned here."""\n'
        "def test_docstring():\n"
        "    assert True\n",
    )
    _write(
        repo,
        "cardre/untracked.py",
        "def hidden(store, art):\n"
        "    return json.loads(store.artifact_path(art).read_text())\n",
    )

    _git(
        repo,
        "add",
        "cardre/prod_reader.py",
        "cardre/alias_reader.py",
        "cardre/_evidence/reader.py",
        "cardre/artifacts.py",
        "cardre/modeling/serialization.py",
        "cardre/custom_io.py",
        "cardre/suppressed.py",
        "cardre/invalid_suppression.py",
        "tests/test_reader.py",
        "tests/test_docstring_scan.py",
        "docs/reference.py",
    )

    module = _load_module()
    monkeypatch.setattr(module, "REPO_ROOT", repo)

    assert module.classify_match("docs/reference.py", None, module.DEFAULT_APPROVED_MODULES) == "documentation_reference"

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        exit_code = module.main(["--json"])

    assert exit_code == 0
    records = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
    classifications = {record["classification"] for record in records}
    pattern_types = {record["pattern_type"] for record in records}

    assert classifications == {
        "approved_low_level_io",
        "false_positive",
        "production_violation",
        "test_violation",
    }
    assert "json_loads_read_text" in pattern_types
    assert "pl_scan_parquet" in pattern_types
    assert "pl_read_parquet" in pattern_types
    assert "open_artifact_path" in pattern_types
    assert "artifact_path_call" in pattern_types

    prod_record = next(
        record
        for record in records
        if record["classification"] == "production_violation" and record["file"] == "cardre/prod_reader.py"
    )
    assert prod_record["suggested_reader"]
    assert prod_record["doc_path"] == "docs/architecture/artifact-evidence-access.md"
    assert prod_record["line_number"] == 4

    alias_record = next(record for record in records if record["file"] == "cardre/alias_reader.py")
    assert alias_record["classification"] == "production_violation"
    assert alias_record["pattern_type"] in {"artifact_path_call", "json_loads_read_text"}

    approved_record = next(record for record in records if record["file"] == "cardre/artifacts.py")
    assert approved_record["classification"] == "approved_low_level_io"

    serialization_record = next(record for record in records if record["file"] == "cardre/modeling/serialization.py")
    assert serialization_record["classification"] == "approved_low_level_io"

    custom_override_buffer = io.StringIO()
    with redirect_stdout(custom_override_buffer):
        exit_code = module.main(["--json", "--approved-modules", "cardre/custom_io.py"])

    assert exit_code == 0
    custom_records = [json.loads(line) for line in custom_override_buffer.getvalue().splitlines() if line.strip()]
    assert any(record["file"] == "cardre/custom_io.py" and record["classification"] == "approved_low_level_io" for record in custom_records)

    invalid_record = next(record for record in records if record["file"] == "cardre/invalid_suppression.py")
    assert invalid_record["invalid_suppression"] is True
    assert invalid_record["classification"] == "production_violation"

    assert all(record["file"] != "docs/reference.py" for record in records)
    assert all(record["file"] != "cardre/untracked.py" for record in records)
    assert all(record["file"] != "tests/test_docstring_scan.py" for record in records)

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        exit_code = module.main(["--json", "--fail-on", "production_violation"])

    assert exit_code == 1
