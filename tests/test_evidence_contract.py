from __future__ import annotations

from cardre.reporting import evidence_contract


def test_canonical_alias_candidates_are_bidirectional():
    assert evidence_contract.canonical_alias_candidates("logistic-regression") == [
        "logistic-regression",
        "model-fit",
    ]
    assert evidence_contract.canonical_alias_candidates("model-fit") == [
        "model-fit",
        "logistic-regression",
    ]


def test_find_evidence_for_canonical_step_tries_legacy_reverse_alias(monkeypatch):
    calls: list[str] = []
    expected = object()

    def fake_latest_successful_run_step(store, plan_version_id, step_id, branch_id=None):
        calls.append(step_id)
        return expected if step_id == "logistic-regression" else None

    monkeypatch.setattr(
        evidence_contract,
        "latest_successful_run_step",
        fake_latest_successful_run_step,
    )

    result = evidence_contract.find_evidence_for_canonical_step(
        store=object(),
        plan_version_id="pv",
        canonical_step_id="model-fit",
        branch_id="branch-1",
    )

    assert result is expected
    assert calls == ["model-fit", "logistic-regression"]
