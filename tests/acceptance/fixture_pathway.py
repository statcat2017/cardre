"""Acceptance-fixture pathway configuration.

The production canonical template is deliberately neutral: it carries no
smoothing, no auto-acceptance of automated bins, and no business metadata.
Real projects supply those decisions through the product. This helper applies
the *acceptance fixture's* specific decisions (tiny synthetic sample needs
additive smoothing, automated bins are accepted, fixed term-loan/retail
business metadata) so engine and acceptance tests that exercise the full
canonical pathway can run on the fixture dataset.

This mirrors what a real user does through the edit loop: configure
define-metadata business metadata, set manual-binning acceptance, and
configure final-WOE smoothing with a rationale.
"""

from __future__ import annotations

from typing import Any

from cardre.domain.plans.scorecard_pathway import (
    build_canonical_scorecard_steps,
    configure_canonical_scorecard,
)

# Tiny synthetic acceptance sample has sparse terminal bins; the final WOE
# pass needs additive smoothing with a rationale to proceed.
_FIXTURE_SMOOTHING: dict[str, Any] = {
    "method": "additive",
    "alpha": 0.5,
    "rationale": "Acceptance fixture uses a tiny synthetic sample with sparse terminal bins",
}


def build_acceptance_fixture_steps(csv_path, cat):
    """Build the canonical pathway configured for the acceptance fixture.

    Returns the same 31-step canonical pathway, with the fixture's specific
    decisions applied (smoothing, automated-bin acceptance, business
    metadata). The import step's ``source_path`` is set to ``csv_path``.
    """
    steps = build_canonical_scorecard_steps(csv_path, cat.resolve)
    return configure_canonical_scorecard(
        steps,
        product="term_loan",
        segment="retail",
        observation_window="2024-01_to_2024-06",
        performance_window="2024-07_to_2024-12",
        reject_inference_position="not_applied",
        accept_automated=True,
        smoothing=_FIXTURE_SMOOTHING,
    )
