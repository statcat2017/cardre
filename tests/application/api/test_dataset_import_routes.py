"""Project-scoped Parquet upload API behavior."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import polars as pl

from tests.application.api.conftest import provision


def _parquet_bytes() -> bytes:
    output = BytesIO()
    pl.DataFrame({"x": [1, 2], "credit_risk_class": ["good", "bad"]}).write_parquet(output)
    return output.getvalue()


def test_imported_dataset_can_create_a_canonical_version_in_its_project(app_env, tmp_path):
    client, container = app_env
    project_id, project_root = provision(container, tmp_path)
    payload = _parquet_bytes()

    uploaded = client.post(
        f"/projects/{project_id}/datasets",
        content=payload,
        headers={
            "Content-Type": "application/octet-stream",
            "X-File-Name": "../../credit.parquet",
        },
    )
    assert uploaded.status_code == 201, uploaded.text
    dataset = uploaded.json()
    assert dataset["file_name"] == "credit.parquet"
    assert dataset["size_bytes"] == len(payload)
    assert dataset["source_ref"].startswith("dataset:")

    plan = client.post(f"/projects/{project_id}/plans", json={"name": "Scorecard"})
    assert plan.status_code == 201, plan.text
    created = client.post(
        f"/projects/{project_id}/plans/{plan.json()['plan_id']}/canonical-version",
        json={"source_ref": dataset["source_ref"]},
    )
    assert created.status_code == 201, created.text

    steps = client.get(
        f"/projects/{project_id}/plan-versions/{created.json()['plan_version_id']}/steps"
    )
    assert steps.status_code == 200
    imported_path = steps.json()[0]["params"]["source_path"]
    assert imported_path == str(container.dataset_store_factory(project_id).resolve_source(dataset["source_ref"]))
    assert project_root.resolve() in Path(imported_path).resolve().parents
    assert Path(imported_path).name != dataset["file_name"]


def test_invalid_dataset_creates_no_project_file(app_env, tmp_path):
    client, container = app_env
    project_id, project_root = provision(container, tmp_path)
    plan = client.post(f"/projects/{project_id}/plans", json={"name": "Scorecard"})
    assert plan.status_code == 201, plan.text

    response = client.post(
        f"/projects/{project_id}/datasets",
        content=b"not parquet",
        headers={"Content-Type": "application/octet-stream", "X-File-Name": "../../bad.parquet"},
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "DATASET_INVALID"
    dataset_dir = project_root / "datasets"
    assert not list(dataset_dir.glob("*.parquet")) if dataset_dir.exists() else True
    assert not list(dataset_dir.glob(".upload-*.tmp")) if dataset_dir.exists() else True
    versions = client.get(f"/projects/{project_id}/plans/{plan.json()['plan_id']}/versions")
    assert versions.status_code == 200
    assert versions.json()["versions"] == []


def test_dataset_reference_cannot_be_used_from_another_project(app_env, tmp_path):
    client, container = app_env
    first_project, _ = provision(container, tmp_path / "first", name="First")
    second_project, second_root = provision(container, tmp_path / "second", name="Second")
    uploaded = client.post(
        f"/projects/{first_project}/datasets",
        content=_parquet_bytes(),
        headers={"Content-Type": "application/octet-stream", "X-File-Name": "credit.parquet"},
    )
    assert uploaded.status_code == 201, uploaded.text

    plan = client.post(f"/projects/{second_project}/plans", json={"name": "Scorecard"})
    assert plan.status_code == 201, plan.text
    rejected = client.post(
        f"/projects/{second_project}/plans/{plan.json()['plan_id']}/canonical-version",
        json={"source_ref": uploaded.json()["source_ref"]},
    )

    assert rejected.status_code == 404
    assert rejected.json()["detail"]["code"] == "DATASET_NOT_FOUND"
    assert not (second_root / "datasets").exists()
