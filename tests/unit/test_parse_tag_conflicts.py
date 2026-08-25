"""Tests for ``core/registry.resolve_tag`` capability-conflict mapping.

The legacy "requires a GUI desktop" phrasing is kept for users / older
tests. ``resolve_tag`` translates the generic ``CapabilityConflictError``
from the solver into that wording. A regression that just lets the
solver's raw message leak through would still be technically correct
but break the user-friendly contract.
"""
from __future__ import annotations

import pytest

from sanity_gravity.core.registry import resolve_tag
from sanity_gravity.domain.tags import Tag


class TestUnknownDimensions:
    def test_unknown_agent(self):
        with pytest.raises(ValueError, match=r"Unknown agent 'zz'"):
            resolve_tag("zz-xfce-kasm")

    def test_unknown_desktop(self):
        with pytest.raises(ValueError, match=r"Unknown desktop 'fake'"):
            resolve_tag("ag-fake-kasm")

    def test_unknown_connector(self):
        with pytest.raises(ValueError, match=r"Unknown connector 'foo'"):
            resolve_tag("ag-xfce-foo")

    def test_format_error(self):
        with pytest.raises(ValueError, match="Invalid tag format"):
            resolve_tag("ag-xfce")

    def test_format_error_extra_part(self):
        with pytest.raises(ValueError, match="Invalid tag format"):
            resolve_tag("ag-xfce-kasm-extra")


class TestCapabilityConflictMapping:
    def test_kasm_with_none_desktop_says_connector_requires_gui(self):
        """``kasm`` connector requires `display`. A ``none`` desktop is
        headless. The error message must name the connector and use
        the user-friendly 'requires a GUI desktop' phrasing."""
        with pytest.raises(ValueError) as exc_info:
            resolve_tag("ag-none-kasm")
        msg = str(exc_info.value)
        assert "Connector 'kasm'" in msg
        assert "requires a GUI desktop" in msg
        assert "headless" in msg

    def test_ag_agent_with_none_desktop_says_agent_requires_gui(self):
        """The ``ag`` agent declares ``requires = ["display"]``. With
        ``ssh`` (which does not provide display) and ``none`` desktop,
        the agent is the missing-capability culprit."""
        with pytest.raises(ValueError) as exc_info:
            resolve_tag("ag-none-ssh")
        msg = str(exc_info.value)
        # When both connector and agent require display, the connector
        # mapping wins (first branch in resolve_tag); for ag-ssh case
        # it's the agent.
        assert "requires a GUI desktop" in msg
        assert "headless" in msg


class TestResolveTagValueBoundary:
    def test_resolve_tag_returns_the_tag_value(self):
        """The registry-validating parse hands back the identity as a
        value: the Tag it already built for the capability solve, not a
        tuple the caller must reassemble.

        Doubles as the happy-path pin for the default tag: it asserts
        the full triple, so anything that could break a bare "does
        ag-xfce-kasm parse" test breaks this one first. The headless
        happy path (``gc-none-ssh``) is pinned by
        test_cli_unit.py::TestDimensionConstraints, which walks every
        headless-capable agent rather than just one.
        """
        parsed = resolve_tag("ag-xfce-kasm")
        assert isinstance(parsed, Tag)
        assert (parsed.agent, parsed.desktop, parsed.connector) == (
            "ag", "xfce", "kasm",
        )

    def test_no_tuple_shim_survives(self):
        """parse_tag existed 'for callers that still unpack tuples' and
        retired when the last one took the Tag directly - which was the
        moment it shipped: zero production callers ever remained. The
        shim stays dead so the tuple shape cannot creep back."""
        import sanity_gravity.core.registry as registry_mod

        assert not hasattr(registry_mod, "parse_tag")
