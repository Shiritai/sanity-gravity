"""ProxyManager on core/proc: the shadow run_command is gone.

systemctl outcomes are explicit Completed matches -- "not enabled" is
the domain answer for every non-zero probe (including rc=127 on hosts
without systemd, where the proxy genuinely is not set up; raising there
would break the graceful proxy-optional up flow). Setup steps that MUST
succeed escalate via raise_for_status, so a broken systemd finally
surfaces as a typed CommandError instead of a silent False/None.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from sanity_gravity.core.proc import Completed
from sanity_gravity.domain.errors import CommandError
from sanity_gravity.infra import proxy_manager as pm_mod


def _completed(rc, out="", err=""):
    return Completed(("systemctl",), rc, stdout=out, stderr=err)


def _pm(tmp_path):
    pm = pm_mod.ProxyManager()
    # Point the unit file somewhere we control.
    pm.unit_file_path = str(tmp_path / "proxy.service")
    return pm


class TestIsEnabled:
    def test_no_unit_file_short_circuits(self, tmp_path):
        pm = _pm(tmp_path)
        with patch.object(pm_mod, "try_run") as tr:
            assert pm.is_enabled() is False
        tr.assert_not_called()

    def test_enabled_answer(self, tmp_path):
        pm = _pm(tmp_path)
        open(pm.unit_file_path, "w").close()
        with patch.object(pm_mod, "try_run",
                          return_value=_completed(0, "enabled")):
            assert pm.is_enabled() is True

    def test_disabled_answer(self, tmp_path):
        pm = _pm(tmp_path)
        open(pm.unit_file_path, "w").close()
        with patch.object(pm_mod, "try_run",
                          return_value=_completed(1, "disabled")):
            assert pm.is_enabled() is False

    def test_no_systemd_host_is_not_enabled(self, tmp_path):
        """rc=127 (systemctl absent): the proxy is genuinely not set up
        on such a host -- explicit tolerance, pinned."""
        pm = _pm(tmp_path)
        open(pm.unit_file_path, "w").close()
        with patch.object(pm_mod, "try_run",
                          return_value=_completed(127, err="not found")):
            assert pm.is_enabled() is False


class TestSetupEscalation:
    def test_systemctl_failure_raises_command_error(self, tmp_path,
                                                    monkeypatch):
        """daemon-reload failing is no longer swallowed into DEVNULL:
        it raises CommandError carrying the stderr."""
        pm = _pm(tmp_path)
        monkeypatch.setattr(pm_mod.shutil, "which",
                            lambda name: "/usr/bin/socat")
        # Redirect every filesystem path into the sandbox.
        pm.bridge_dir = str(tmp_path / "bridge")
        pm.socket_path = str(tmp_path / "bridge" / "ssh.sock")

        with patch.object(
            pm_mod, "try_run",
            return_value=_completed(1, err="Failed to connect to bus"),
        ):
            with pytest.raises(CommandError) as ei:
                pm.setup()
        assert ei.value.returncode == 1
        assert "bus" in ei.value.stderr


class TestProxySetupVerbFailure:
    def test_setup_failure_exits_nonzero_via_sanity_error(self):
        """The old verb printed 'Setup failed' and returned None ->
        exit 0 on a failed setup. It now raises, so the boundary exits
        nonzero."""
        import argparse
        from unittest.mock import MagicMock

        from sanity_gravity.domain.errors import SanityError
        from sanity_gravity.verbs import proxy as proxy_mod

        fake_pm = MagicMock()
        fake_pm.setup.side_effect = RuntimeError("permission denied")
        with patch.object(proxy_mod, "ProxyManager", return_value=fake_pm), \
             patch.object(proxy_mod, "print_header"):
            with pytest.raises(SanityError) as ei:
                proxy_mod.proxy_setup_cmd(argparse.Namespace())
        assert "permission denied" in str(ei.value)
        assert ei.value.exit_code == 1
