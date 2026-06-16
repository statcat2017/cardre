"""Pytest configuration and markers for optional dependency tests."""

import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "optional_boosting: tests requiring xgboost/lightgbm/catboost")
    config.addinivalue_line("markers", "optional_imbalance: tests requiring imbalanced-learn")
    config.addinivalue_line("markers", "optional_explain: tests requiring shap/lime")
    config.addinivalue_line("markers", "optional_deep: tests requiring torch")
