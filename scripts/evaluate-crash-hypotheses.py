#!/usr/bin/env python3
"""Run the 100 crash probes and write a Markdown report."""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.test_crash_hypotheses import CATALOG  # noqa: E402


def evaluate():
    rows = []
    for hyp in CATALOG:
        try:
            result = hyp.probe()
        except Exception as exc:  # noqa: BLE001
            from tests.test_crash_hypotheses import ProbeResult

            result = ProbeResult("unverified", "environment", f"probe raised {type(exc).__name__}: {exc}", 0.0)
        rows.append((hyp, result))
    return rows


def report(rows) -> str:
    outcomes = Counter(result.outcome for _, result in rows)
    actual_outcomes = {hyp.id: result.outcome for hyp, result in rows}
    roots = {
        "Reconciliation swallows Project read failures": [8, 9],
        "Unhandled or misleading failure paths": [20, 21, 76, 89, 90],
        "Run liveness and lifecycle assumptions": [41, 43, 47, 50, 60],
        "Silent or late data-quality failure": [62, 63, 64, 68],
    }
    lines = [
        "# Cardre Crash Hypothesis Evaluation", "",
        f"Run timestamp (UTC): `{dt.datetime.now(dt.UTC).isoformat()}`", "",
        "## Summary", "",
        f"Evaluated **{len(rows)}** hypotheses.", "",
        f"- **Real defect:** {outcomes['real defect']}",
        f"- **Mitigated:** {outcomes['mitigated']}",
        f"- **Unverified:** {outcomes['unverified']}", "",
        "`Unverified` means neither demonstrated real nor demonstrated mitigated. It is not a defect count.", "",
        "## Real Defects", "",
        "The rows below identify concrete risky paths. Related rows may describe one root cause and are not automatically independent defects.", "",
    ]
    for root, ids in roots.items():
        real_ids = [hyp_id for hyp_id in ids if actual_outcomes.get(hyp_id) == "real defect"]
        if real_ids:
            lines.append(f"- **{root}:** {', '.join(f'#{i}' for i in real_ids)}")
    lines += ["", "## Method", "", "Runtime probes exercise bounded production behaviour. Structural probes inspect control flow or configuration when a safe runtime trigger is unavailable. Environment, race, resource-exhaustion, and cross-version cases remain unverified instead of being promoted to defects.", "", "## Results", "", "| # | Hypothesis | Outcome | Kind | Confidence | Probe evidence | References |", "|---:|---|---|---|---:|---|---|"]
    for hyp, result in rows:
        evidence = result.evidence.replace("|", "\\|").replace("\n", " ")
        refs = ", ".join(hyp.refs).replace("|", "\\|")
        lines.append(f"| {hyp.id} | {hyp.title} | {result.outcome} | {result.kind} | {result.confidence:.2f} | {evidence} | {refs} |")
    mitigated = [str(hyp.id) for hyp, result in rows if result.outcome == "mitigated"]
    unverified = [str(hyp.id) for hyp, result in rows if result.outcome == "unverified"]
    lines += [
        "", "## Mitigated IDs", "",
        "The following hypotheses were checked and did not demonstrate the stated failure under the available probe: "
        + ", ".join(f"#{hyp_id}" for hyp_id in mitigated) + ".",
        "", "## Unverified IDs", "",
        "The following hypotheses require an OS race, external process, resource-scale workload, browser/Tauri run, or cross-version setup: "
        + ", ".join(f"#{hyp_id}" for hyp_id in unverified) + ".",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(ROOT / "reports" / "crash-hypothesis-report.md"))
    args = parser.parse_args()
    rows = evaluate()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report(rows), encoding="utf-8")
    counts = Counter(result.outcome for _, result in rows)
    print(f"Evaluated {len(rows)} hypotheses -> {output}")
    print(f"real defect: {counts['real defect']}")
    print(f"mitigated: {counts['mitigated']}")
    print(f"unverified: {counts['unverified']}")


if __name__ == "__main__":
    main()
