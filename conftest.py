"""Pytest configuration and markers."""

import pytest


def pytest_configure(config):
    # Optional dependency markers
    config.addinivalue_line("markers", "optional_boosting: tests requiring xgboost/lightgbm/catboost")
    config.addinivalue_line("markers", "optional_imbalance: tests requiring imbalanced-learn")
    config.addinivalue_line("markers", "optional_explain: tests requiring shap/lime")
    config.addinivalue_line("markers", "optional_deep: tests requiring torch")
    # Suite organisation markers
    config.addinivalue_line("markers", "slow: tests that take longer to run")
    config.addinivalue_line("markers", "api: sidecar API integration tests")
    config.addinivalue_line("markers", "e2e: end-to-end acceptance tests")
    config.addinivalue_line("markers", "regression: safety-rail / canary tests")
