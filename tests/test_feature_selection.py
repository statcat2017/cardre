"""Tests for feature-selection node preparation migration.

Filter and embedded feature selection nodes now use the shared supervised
training preparation module. Existing executor-level tests exercise those
paths; this file provides a home for node-level coverage when needed.
"""
