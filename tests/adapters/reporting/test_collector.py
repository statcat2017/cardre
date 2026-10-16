from cardre.adapters.reporting.collector import _set_variable_summary_counts
from cardre.application.reporting.schema import ReportBundle, VariableInfo


def test_variable_summary_counts_follow_included_and_excluded_statuses():
    bundle = ReportBundle(
        project_id="project",
        run_id="run",
        variables=[
            VariableInfo(variable_name="included", role="included"),
            VariableInfo(variable_name="rejected", role="REJECTED"),
            VariableInfo(variable_name="excluded", role="excluded"),
        ],
    )

    _set_variable_summary_counts(bundle)

    assert bundle.summary.final_variable_count == 1
    assert bundle.summary.excluded_variable_count == 2
