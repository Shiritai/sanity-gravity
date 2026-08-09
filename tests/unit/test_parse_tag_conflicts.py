"""Tests for ``cli/registry.parse_tag`` capability-conflict mapping.

The legacy "requires a GUI desktop" phrasing is kept for users / older
tests. ``parse_tag`` translates the generic ``CapabilityConflictError``
from the solver into that wording. A regression that just lets the
solver's raw message leak through would still be technically correct
but break the user-friendly contract.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from sanity_gravity.cli.registry import parse_tag  # noqa: E402


class TestUnknownDimensions:
    def test_unknown_agent(self):
        with pytest.raises(ValueError, match=r"Unknown agent 'zz'"):
            parse_tag("zz-xfce-kasm")

    def test_unknown_desktop(self):
        with pytest.raises(ValueError, match=r"Unknown desktop 'fake'"):
            parse_tag("ag-fake-kasm")

    def test_unknown_connector(self):
        with pytest.raises(ValueError, match=r"Unknown connector 'foo'"):
            parse_tag("ag-xfce-foo")

    def test_format_error(self):
        with pytest.raises(ValueError, match="Invalid tag format"):
            parse_tag("ag-xfce")

    def test_format_error_extra_part(self):
        # Five parts is one too many for the {base-}agent-desktop-connector
        # grammar; four parts is now a valid (base) dimension tag.
        with pytest.raises(ValueError, match="Invalid tag format"):
            parse_tag("a-b-c-d-e")

    def test_unknown_base_image(self):
        with pytest.raises(ValueError, match=r"Unknown base image 'ag'"):
            parse_tag("ag-xfce-kasm-extra")


class TestCapabilityConflictMapping:
    def test_kasm_with_none_desktop_says_connector_requires_gui(self):
        """``kasm`` connector requires `display`. A ``none`` desktop is
        headless. The error message must name the connector and use
        the user-friendly 'requires a GUI desktop' phrasing."""
        with pytest.raises(ValueError) as exc_info:
            parse_tag("ag-none-kasm")
        msg = str(exc_info.value)
        assert "Connector 'kasm'" in msg
        assert "requires a GUI desktop" in msg
        assert "headless" in msg

    def test_vnc_with_none_desktop_says_connector_requires_gui(self):
        """Same mapping for the ``vnc`` connector."""
        with pytest.raises(ValueError) as exc_info:
            parse_tag("ag-none-vnc")
        msg = str(exc_info.value)
        assert "Connector 'vnc'" in msg
        assert "requires a GUI desktop" in msg

    def test_ag_agent_with_none_desktop_says_agent_requires_gui(self):
        """The ``ag`` agent declares ``requires = ["display"]``. With
        ``ssh`` (which does not provide display) and ``none`` desktop,
        the agent is the missing-capability culprit."""
        with pytest.raises(ValueError) as exc_info:
            parse_tag("ag-none-ssh")
        msg = str(exc_info.value)
        # When both connector and agent require display, the connector
        # mapping wins (first branch in parse_tag); for ag-ssh case
        # it's the agent.
        assert "requires a GUI desktop" in msg
        assert "headless" in msg


class TestHappyPath:
    def test_default_tag_parses(self):
        base, agent, desktop, connector = parse_tag("ag-xfce-kasm")
        assert (base, agent, desktop, connector) == ("ubuntu", "ag", "xfce", "kasm")

    def test_debian_tag_parses(self):
        base, agent, desktop, connector = parse_tag("debian-ag-xfce-kasm")
        assert (base, agent, desktop, connector) == ("debian", "ag", "xfce", "kasm")

    def test_headless_combo_ssh(self):
        # gc agent + none desktop + ssh connector — none of these
        # require display. Must succeed.
        base, agent, desktop, connector = parse_tag("gc-none-ssh")
        assert (base, agent, desktop, connector) == ("ubuntu", "gc", "none", "ssh")
