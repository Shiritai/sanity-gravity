"""Unit coverage for the light controller verbs that the rest of the
suite ignored: ``check``, ``proxy_*``, ``ide``, ``test``.

These verbs are short and almost-pure: mocking ``run_command``,
``shutil.which``, ``ProxyManager``, ``subprocess.check_call`` and a few
print helpers is enough to exercise their error paths.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))


# ---------------------------------------------------------------------------
# verbs/check.py
# ---------------------------------------------------------------------------


class TestCheckPrereqs:
    """Cover the three sequential checks: docker / compose / daemon."""

    def _args(self):
        return argparse.Namespace()

    def test_docker_missing_exits_with_message(self):
        from sanity_gravity.verbs import check as check_mod

        with patch.object(check_mod.shutil, "which", return_value=None), \
             patch.object(check_mod, "print_error") as err, \
             patch.object(check_mod, "print_header"), \
             patch.object(check_mod, "print_success"):
            with pytest.raises(SystemExit) as ei:
                check_mod.check_prereqs(self._args())
            assert ei.value.code == 1
            err.assert_called_once()
            assert "Docker is NOT installed" in err.call_args[0][0]

    def test_compose_unavailable_reports_and_exits(self):
        from sanity_gravity.verbs import check as check_mod

        def fake_run(cmd, **_kw):
            if cmd[1] == "compose":
                raise FileNotFoundError("docker-compose plugin missing")
            return ""

        with patch.object(check_mod.shutil, "which", return_value="/usr/bin/docker"), \
             patch.object(check_mod, "run_command", side_effect=fake_run), \
             patch.object(check_mod, "print_error") as err, \
             patch.object(check_mod, "print_header"), \
             patch.object(check_mod, "print_success"):
            with pytest.raises(SystemExit) as ei:
                check_mod.check_prereqs(self._args())
            assert ei.value.code == 1
            assert "Docker Compose is NOT installed" in err.call_args[0][0]

    def test_daemon_down_reports_and_exits(self):
        from sanity_gravity.verbs import check as check_mod

        def fake_run(cmd, **_kw):
            if cmd[1] == "info":
                raise subprocess.CalledProcessError(
                    1, cmd, output="", stderr="Cannot connect to the Docker daemon"
                )
            return ""

        with patch.object(check_mod.shutil, "which", return_value="/usr/bin/docker"), \
             patch.object(check_mod, "run_command", side_effect=fake_run), \
             patch.object(check_mod, "print_error") as err, \
             patch.object(check_mod, "print_header"), \
             patch.object(check_mod, "print_success"):
            with pytest.raises(SystemExit) as ei:
                check_mod.check_prereqs(self._args())
            assert ei.value.code == 1
            assert "Docker Daemon is NOT running" in err.call_args[0][0]

    def test_all_present_does_not_exit(self):
        from sanity_gravity.verbs import check as check_mod

        with patch.object(check_mod.shutil, "which", return_value="/usr/bin/docker"), \
             patch.object(check_mod, "run_command", return_value=""), \
             patch.object(check_mod, "print_error"), \
             patch.object(check_mod, "print_header"), \
             patch.object(check_mod, "print_success") as ok:
            # Must not raise.
            check_mod.check_prereqs(self._args())
            # Three success calls: docker / compose / daemon.
            assert ok.call_count == 3


# ---------------------------------------------------------------------------
# verbs/proxy.py
# ---------------------------------------------------------------------------


class TestProxyVerbs:
    """Cover the three proxy verbs: setup / status / remove."""

    def test_setup_when_proxymanager_missing(self):
        from sanity_gravity.verbs import proxy as proxy_mod

        with patch.object(proxy_mod, "ProxyManager", None), \
             patch.object(proxy_mod, "print_error") as err:
            proxy_mod.proxy_setup_cmd(argparse.Namespace())
            err.assert_called_once_with("ProxyManager library not found.")

    def test_setup_success_path(self):
        from sanity_gravity.verbs import proxy as proxy_mod

        fake_pm = MagicMock()
        fake_pm.get_socket_path.return_value = "/tmp/sock"
        with patch.object(proxy_mod, "ProxyManager", return_value=fake_pm), \
             patch.object(proxy_mod, "print_error") as err, \
             patch.object(proxy_mod, "print_success") as ok, \
             patch.object(proxy_mod, "print_header"), \
             patch.object(proxy_mod, "print_info"):
            proxy_mod.proxy_setup_cmd(argparse.Namespace())
            fake_pm.setup.assert_called_once()
            ok.assert_called_once()
            err.assert_not_called()

    def test_setup_failure_caught_and_reported(self):
        from sanity_gravity.verbs import proxy as proxy_mod

        fake_pm = MagicMock()
        fake_pm.setup.side_effect = RuntimeError("permission denied")
        with patch.object(proxy_mod, "ProxyManager", return_value=fake_pm), \
             patch.object(proxy_mod, "print_error") as err, \
             patch.object(proxy_mod, "print_success") as ok, \
             patch.object(proxy_mod, "print_header"), \
             patch.object(proxy_mod, "print_info"):
            # Must not raise — proxy_setup_cmd handles the exception itself.
            proxy_mod.proxy_setup_cmd(argparse.Namespace())
            err.assert_called_once()
            assert "permission denied" in err.call_args[0][0]
            ok.assert_not_called()

    def test_status_renders_each_section(self, capsys):
        from sanity_gravity.verbs import proxy as proxy_mod

        fake_pm = MagicMock()
        fake_pm.get_status.return_value = {
            "setup": True,
            "active": True,
            "socket_exists": True,
            "agent_reachable": True,
            "error": None,
        }
        fake_pm.get_socket_path.return_value = "/tmp/sock"
        with patch.object(proxy_mod, "ProxyManager", return_value=fake_pm), \
             patch.object(proxy_mod, "print_header"):
            proxy_mod.proxy_status_cmd(argparse.Namespace())
        out = capsys.readouterr().out
        assert "Service:" in out and "Active:" in out
        assert "Socket:" in out and "Agent:" in out

    def test_status_when_proxymanager_missing(self):
        from sanity_gravity.verbs import proxy as proxy_mod

        with patch.object(proxy_mod, "ProxyManager", None), \
             patch.object(proxy_mod, "print_error") as err:
            proxy_mod.proxy_status_cmd(argparse.Namespace())
            err.assert_called_once()

    def test_remove_when_proxymanager_missing(self):
        from sanity_gravity.verbs import proxy as proxy_mod

        with patch.object(proxy_mod, "ProxyManager", None), \
             patch.object(proxy_mod, "print_error") as err:
            proxy_mod.proxy_remove_cmd(argparse.Namespace())
            err.assert_called_once()


# ---------------------------------------------------------------------------
# verbs/ide.py
# ---------------------------------------------------------------------------


class TestIdeVerb:
    """Cover the early-return paths and the docker-cp injection failure."""

    def _args(self, name="sanity-gravity", ide_command="diag"):
        args = {"ide_command": ide_command}
        if name is not None:
            args["name"] = name
        return argparse.Namespace(**args)

    def test_no_active_projects(self):
        from sanity_gravity.verbs import ide as ide_mod

        with patch.object(ide_mod, "get_active_projects", return_value=[]), \
             patch.object(ide_mod, "print_error") as err:
            ide_mod.ide_cmd(self._args(name=None))
            err.assert_called_once()
            assert "No active managed projects" in err.call_args[0][0]

    def test_multiple_active_projects_requires_name(self):
        from sanity_gravity.verbs import ide as ide_mod

        with patch.object(ide_mod, "get_active_projects",
                          return_value=["p1", "p2"]), \
             patch.object(ide_mod, "print_error") as err:
            ide_mod.ide_cmd(self._args(name=None))
            err.assert_called_once()
            assert "Multiple active projects" in err.call_args[0][0]

    def test_named_project_not_active(self):
        from sanity_gravity.verbs import ide as ide_mod

        with patch.object(ide_mod, "get_active_projects",
                          return_value=["other"]), \
             patch.object(ide_mod, "print_error") as err:
            ide_mod.ide_cmd(self._args(name="missing"))
            err.assert_called_once()
            assert "not active or managed" in err.call_args[0][0]

    def test_no_running_container(self):
        from sanity_gravity.verbs import ide as ide_mod

        with patch.object(ide_mod, "get_active_projects",
                          return_value=["proj1"]), \
             patch.object(ide_mod, "run_command", return_value="false"), \
             patch.object(ide_mod, "print_error") as err:
            ide_mod.ide_cmd(self._args(name="proj1"))
            err.assert_called_once()
            assert "No running containers" in err.call_args[0][0]

    def test_provides_ide_without_manifest_section_errors(self):
        """An agent may claim the 'ide' capability yet ship no [ide]
        contract; the verb must fail with a clear message instead of
        falling back to another plugin's tooling."""
        from sanity_gravity.plugins.manifest import PluginManifest
        from sanity_gravity.verbs import ide as ide_mod

        broken = PluginManifest(
            slug="ag", name="ag", kind="agent", api_version="1",
            provides=("ide",), requires=(), dockerfile="Dockerfile",
        )
        registry = MagicMock()
        registry.agents = {"ag": broken}
        # parse_tag validates all four dimensions against the registry;
        # provide the companion buckets so the tag resolves to ``ag``.
        registry.desktops = {"none": None, "xfce": None}
        registry.connectors = {"kasm": None, "ssh": None, "vnc": None}
        registry.base_images = {}

        with patch.object(ide_mod, "get_active_projects",
                          return_value=["proj1"]), \
             patch.object(ide_mod, "run_command", return_value="true"), \
             patch("sanity_gravity.cli.registry.get_registry",
                   return_value=registry), \
             patch.object(ide_mod.subprocess, "check_call") as check_call, \
             patch.object(ide_mod, "print_error") as err:
            ide_mod.ide_cmd(self._args(name="proj1"))
            check_call.assert_not_called()
            err.assert_called_once()
            assert "[ide]" in err.call_args[0][0]

    def test_inject_failure_exits(self):
        from sanity_gravity.verbs import ide as ide_mod

        # The first variant in VALID_TAGS will report Running=true.
        with patch.object(ide_mod, "get_active_projects",
                          return_value=["proj1"]), \
             patch.object(ide_mod, "run_command", return_value="true"), \
             patch.object(ide_mod.subprocess, "check_call",
                          side_effect=subprocess.CalledProcessError(1, "docker cp")), \
             patch.object(ide_mod, "print_error") as err, \
             patch.object(ide_mod, "print_header"), \
             patch.object(ide_mod, "print_info"):
            with pytest.raises(SystemExit) as ei:
                ide_mod.ide_cmd(self._args(name="proj1"))
            assert ei.value.code == 1
            err.assert_called_once()
            assert "hot-inject" in err.call_args[0][0]


# ---------------------------------------------------------------------------
# verbs/test_suite.py
# ---------------------------------------------------------------------------


class TestTestSuiteVerb:
    """Cover the pytest-import-failure and exit-code propagation paths."""

    def test_missing_pytest_exits_one(self):
        from sanity_gravity.verbs import test_suite as ts_mod

        # Force the local ``import pytest`` inside ``test_suite`` to fail
        # by making pytest temporarily un-importable.
        original = sys.modules.pop("pytest", None)
        sys.modules["pytest"] = None  # type: ignore[assignment]
        try:
            with patch.object(ts_mod, "print_error") as err, \
                 patch.object(ts_mod, "print_header"):
                with pytest.raises(SystemExit) as ei:
                    ts_mod.test_suite(argparse.Namespace(target=None))
            assert ei.value.code == 1
            err.assert_called_once()
            assert "pytest is not installed" in err.call_args[0][0]
        finally:
            if original is not None:
                sys.modules["pytest"] = original
            else:
                sys.modules.pop("pytest", None)

    def test_pytest_nonzero_propagates_exit(self):
        from sanity_gravity.verbs import test_suite as ts_mod

        with patch("pytest.main", return_value=2), \
             patch.object(ts_mod, "print_header"):
            with pytest.raises(SystemExit) as ei:
                ts_mod.test_suite(argparse.Namespace(target=None))
            assert ei.value.code == 2

    def test_pytest_zero_does_not_exit(self):
        from sanity_gravity.verbs import test_suite as ts_mod

        with patch("pytest.main", return_value=0), \
             patch.object(ts_mod, "print_header"):
            # Must complete without raising.
            ts_mod.test_suite(argparse.Namespace(target="tests/unit"))
