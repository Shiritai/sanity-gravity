"""Tests for ``compose/generators.py`` write-failure propagation.

The generators delegate the actual write to ``ComposeBuilder.write``,
which calls ``os.makedirs(...)`` then ``open(path, 'w')``. Both can
raise :class:`OSError` (read-only filesystem, denied permissions, full
disk). The generators *intentionally* do not swallow these — the up
flow needs to abort if the compose overlay cannot be persisted, rather
than silently continue with a stale file. These tests pin that
contract so a future "swallow and continue" patch fails loudly.
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from sanity_gravity.compose import generators as gen_mod
from sanity_gravity.compose.builder import ComposeBuilder, ComposeService


@pytest.fixture
def isolated_cwd(tmp_path, monkeypatch):
    """Run generators in a fresh cwd so they don't pollute the repo root."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestComposeBuilderWriteFailures:
    def test_write_to_read_only_path_raises(self, tmp_path):
        ro_dir = tmp_path / "ro"
        ro_dir.mkdir()
        # Make the directory non-writable. Skip on platforms where chmod
        # is meaningless (e.g. some Windows filesystems).
        os.chmod(ro_dir, 0o555)
        try:
            builder = ComposeBuilder().add_service(ComposeService(name="x", image="i"))
            with pytest.raises(OSError):
                builder.write(str(ro_dir / "compose.yml"))
        finally:
            os.chmod(ro_dir, 0o755)

    def test_write_propagates_makedirs_oserror(self, tmp_path):
        builder = ComposeBuilder().add_service(ComposeService(name="x", image="i"))
        with patch("os.makedirs", side_effect=OSError("disk full")):
            with pytest.raises(OSError, match="disk full"):
                builder.write(str(tmp_path / "sub" / "compose.yml"))


class TestGeneratorsPropagate:
    def test_generate_resource_compose_propagates_write_oserror(self, isolated_cwd):
        with patch.object(ComposeBuilder, "write",
                          side_effect=OSError("read-only filesystem")):
            with pytest.raises(OSError, match="read-only filesystem"):
                gen_mod.generate_resource_compose("1.5", "4G", "ag-xfce-kasm")

    def test_generate_resource_compose_returns_none_when_no_args(self, isolated_cwd):
        # Documented short-circuit: cpus & memory both unset -> None.
        assert gen_mod.generate_resource_compose(None, None, "ag-xfce-kasm") is None

    def test_generate_compose_for_tag_propagates_write_oserror(self, isolated_cwd):
        with patch.object(ComposeBuilder, "write",
                          side_effect=OSError("permission denied")):
            with pytest.raises(OSError, match="permission denied"):
                gen_mod.generate_compose_for_tag("ag-xfce-kasm")
