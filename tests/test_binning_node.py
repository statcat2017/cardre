from __future__ import annotations

import pytest

from cardre.nodes.build.automatic import AutomaticBinningNode


class TestAutomaticBinningNodeValidateParams:
    @pytest.fixture
    def node(self):
        return AutomaticBinningNode()

    def test_valid_fine_classing(self, node):
        errors = node.validate_params({"method": "fine_classing", "max_bins": 20, "min_bin_fraction": 0.05})
        assert errors == []

    @pytest.mark.skip(reason="Requires optbinning optional dependency")
    def test_valid_optbinning_no_engine_check(self, node):
        errors = node.validate_params({"method": "optbinning"})
        assert errors == []

    def test_invalid_method(self, node):
        errors = node.validate_params({"method": "invalid_method"})
        assert "invalid_method" in errors[0]

    def test_fine_classing_max_bins_too_small(self, node):
        errors = node.validate_params({"method": "fine_classing", "max_bins": 1})
        assert any("max_bins" in e for e in errors)

    def test_fine_classing_max_bins_invalid_type(self, node):
        errors = node.validate_params({"method": "fine_classing", "max_bins": "abc"})
        assert any("max_bins" in e for e in errors)

    def test_fine_classing_min_bin_fraction_bounds(self, node):
        errors = node.validate_params({"method": "fine_classing", "min_bin_fraction": 1.5})
        assert any("min_bin_fraction" in e for e in errors)

    def test_fine_classing_min_bin_fraction_invalid_type(self, node):
        errors = node.validate_params({"method": "fine_classing", "min_bin_fraction": "abc"})
        assert any("min_bin_fraction" in e for e in errors)

    def test_fine_classing_missing_policy_invalid(self, node):
        errors = node.validate_params({"method": "fine_classing", "missing_policy": "drop"})
        assert any("missing_policy" in e for e in errors)

    def test_fine_classing_max_cat_levels_too_small(self, node):
        errors = node.validate_params({"method": "fine_classing", "max_categorical_levels": 0})
        assert any("max_categorical_levels" in e for e in errors)

    def test_fine_classing_max_cat_levels_invalid_type(self, node):
        errors = node.validate_params({"method": "fine_classing", "max_categorical_levels": "abc"})
        assert any("max_categorical_levels" in e for e in errors)

    def test_optbinning_engine_invalid(self, node):
        errors = node.validate_params({"method": "optbinning", "engine": "fake"})
        assert any("engine" in e for e in errors)

    def test_optbinning_prebinning_method_invalid(self, node):
        errors = node.validate_params({"method": "optbinning", "prebinning_method": "kmeans"})
        assert any("prebinning_method" in e for e in errors)

    def test_optbinning_solver_invalid(self, node):
        errors = node.validate_params({"method": "optbinning", "solver": "invalid"})
        assert any("solver" in e for e in errors)

    def test_optbinning_divergence_invalid(self, node):
        errors = node.validate_params({"method": "optbinning", "divergence": "invalid"})
        assert any("divergence" in e for e in errors)

    def test_optbinning_monotonic_trend_invalid(self, node):
        errors = node.validate_params({"method": "optbinning", "monotonic_trend": "invalid"})
        assert any("monotonic_trend" in e for e in errors)

    def test_optbinning_max_n_prebins_bad(self, node):
        errors = node.validate_params({"method": "optbinning", "max_n_prebins": 0})
        assert any("max_n_prebins" in e for e in errors)

    def test_optbinning_min_prebin_size_bad(self, node):
        errors = node.validate_params({"method": "optbinning", "min_prebin_size": -1})
        assert any("min_prebin_size" in e for e in errors)

    def test_optbinning_min_prebin_size_type_error(self, node):
        errors = node.validate_params({"method": "optbinning", "min_prebin_size": "abc"})
        assert any("min_prebin_size" in e for e in errors)


class TestAutomaticBinningNodeRun:
    def test_run_unknown_method_raises(self):
        node = AutomaticBinningNode()
        from cardre.execution.context import ExecutionContext
        with pytest.raises(ValueError, match="Unknown binning method"):
            node.run(
                ExecutionContext(
                    store=None, run_id="r", plan_version_id="pv",
                    step_spec=None, parent_run_steps=[],
                    input_artifacts=[], validated_params={"method": "bogus"},
                    runtime_metadata={},
                )
            )

    def test_run_optbinning_dispatch(self, monkeypatch):
        """Assert that method='optbinning' dispatches to _run_optbinning."""
        import cardre.nodes.build.automatic as automatic_mod
        called = False

        def fake_optbinning(ctx):
            nonlocal called
            called = True
            from cardre.execution.context import NodeOutput
            return NodeOutput(artifacts=[], metrics={})

        monkeypatch.setattr(automatic_mod, "_run_optbinning", fake_optbinning)
        node = AutomaticBinningNode()
        from cardre.execution.context import ExecutionContext
        node.run(
            ExecutionContext(
                store=None, run_id="r", plan_version_id="pv",
                step_spec=None, parent_run_steps=[],
                input_artifacts=[], validated_params={"method": "optbinning"},
                runtime_metadata={},
            )
        )
        assert called, "_run_optbinning was not invoked for method='optbinning'"
