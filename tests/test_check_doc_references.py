"""Tests for the doc-reference guardrail."""

from __future__ import annotations

import sys
from pathlib import Path


# Add scripts/ to path so we can import the guardrail module
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from check_doc_references import (  # noqa: E402
    MARKDOWN_LINK_PATTERN,
    KNOWN_EXCEPTIONS,
    REPO_ROOT,
    resolve_link_target,
)


class TestResolveLinkTarget:
    """Verify relative Markdown link resolution."""

    def test_relative_link_from_docs_readme(self) -> None:
        """[Reporting](architecture/reporting.md) from docs/README.md resolves to docs/architecture/reporting.md"""
        source = REPO_ROOT / "docs/README.md"
        result = resolve_link_target(source, "architecture/reporting.md")
        assert result == "docs/architecture/reporting.md"

    def test_parent_link_from_docs_readme(self) -> None:
        """[README](../README.md) from docs/README.md resolves to README.md"""
        source = REPO_ROOT / "docs/README.md"
        result = resolve_link_target(source, "../README.md")
        assert result == "README.md"

    def test_external_url_returns_none(self) -> None:
        """External URLs should be skipped."""
        source = REPO_ROOT / "docs/README.md"
        result = resolve_link_target(source, "https://example.com")
        assert result is None

    def test_anchor_only_returns_none(self) -> None:
        """Anchor-only links should be skipped."""
        source = REPO_ROOT / "docs/README.md"
        result = resolve_link_target(source, "#section")
        assert result is None

    def test_relative_link_from_root_readme(self) -> None:
        """[docs](docs/) from README.md resolves to docs (trailing slash normalized)"""
        source = REPO_ROOT / "README.md"
        result = resolve_link_target(source, "docs/")
        assert result == "docs"

    def test_broken_relative_link(self) -> None:
        """A non-existent relative link should still resolve to a path."""
        source = REPO_ROOT / "docs/README.md"
        result = resolve_link_target(source, "nonexistent/file.md")
        assert result == "docs/nonexistent/file.md"


class TestMarkdownLinkPattern:
    """Verify the Markdown link regex captures targets correctly."""

    def test_captures_relative_link(self) -> None:
        text = "[Reporting](architecture/reporting.md)"
        match = MARKDOWN_LINK_PATTERN.search(text)
        assert match is not None
        assert match.group(2) == "architecture/reporting.md"

    def test_captures_parent_link(self) -> None:
        text = "[README](../README.md)"
        match = MARKDOWN_LINK_PATTERN.search(text)
        assert match is not None
        assert match.group(2) == "../README.md"

    def test_captures_link_with_anchor(self) -> None:
        text = "[Section](file.md#anchor)"
        match = MARKDOWN_LINK_PATTERN.search(text)
        assert match is not None
        assert match.group(2) == "file.md#anchor"

    def test_captures_external_url(self) -> None:
        text = "[Example](https://example.com)"
        match = MARKDOWN_LINK_PATTERN.search(text)
        assert match is not None
        assert match.group(2) == "https://example.com"


class TestKnownExceptions:
    """Verify KNOWN_EXCEPTIONS does not contain future-doc paths."""

    def test_no_future_doc_exceptions(self) -> None:
        """Future doc paths should not be whitelisted."""
        future_paths = {
            "docs/architecture/manual-binning.md",
            "docs/architecture/workflow-guidance.md",
            "docs/adr/README.md",
        }
        for path in future_paths:
            assert path not in KNOWN_EXCEPTIONS, (
                f"{path} should not be in KNOWN_EXCEPTIONS — "
                "future docs should not be whitelisted"
            )
