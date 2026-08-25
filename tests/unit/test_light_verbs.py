"""Unit coverage for the light controller verbs that the rest of the
suite ignored: ``check``, ``proxy_*``, ``ide``, ``test``.

These verbs are short and almost-pure: the ``fake_proc`` boundary plus
mocked ``shutil.which``, ``ProxyManager``, ``subprocess.check_call`` and
a few print helpers is enough to exercise their error paths.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# verbs/check.py
# ---------------------------------------------------------------------------


class TestCheckPrereqs:
    """Cover the three sequential checks: docker / compose / daemon.

    Each probe is scripted by its own command shape rather than by a
    blanket "everything succeeds" fake, so a check that stops issuing
    its probe -- or issues a different one -- shows up instead of
    silently passing.
    """

    def _args(self):
        return argparse.Namespace()

    def test_docker_missing_raises_with_hint(self):
        from sanity_gravity.domain.errors import SanityError
        from sanity_gravity.verbs import check as check_mod

        with patch.object(check_mod.shutil, "which", return_value=None), \
             patch.object(check_mod, "print_header"), \
             patch.object(check_mod, "print_success"):
            with pytest.raises(SanityError) as ei:
                check_mod.check_prereqs(self._args())
            assert ei.value.exit_code == 1
            assert "Docker is NOT installed" in str(ei.value)
            assert "install" in (ei.value.hint or "").lower()

    def test_compose_unavailable_raises(self, fake_proc):
        from sanity_gravity.domain.errors import SanityError
        from sanity_gravity.verbs import check as check_mod

        # Missing compose plugin: try_run maps it to rc=127.
        fake_proc.script("docker compose version", rc=127,
                         stderr="docker-compose plugin missing")

        with patch.object(check_mod.shutil, "which", return_value="/usr/bin/docker"), \
             patch.object(check_mod, "print_header"), \
             patch.object(check_mod, "print_success"):
            with pytest.raises(SanityError) as ei:
                check_mod.check_prereqs(self._args())
            assert ei.value.exit_code == 1
            assert "Docker Compose is NOT installed" in str(ei.value)

    def test_daemon_down_raises_with_hint(self, fake_proc):
        from sanity_gravity.domain.errors import SanityError
        from sanity_gravity.verbs import check as check_mod

        fake_proc.script("docker compose version", rc=0)
        fake_proc.script("docker info", rc=1,
                         stderr="Cannot connect to the Docker daemon")

        with patch.object(check_mod.shutil, "which", return_value="/usr/bin/docker"), \
             patch.object(check_mod, "print_header"), \
             patch.object(check_mod, "print_success"):
            with pytest.raises(SanityError) as ei:
                check_mod.check_prereqs(self._args())
            assert ei.value.exit_code == 1
            assert "Docker Daemon is NOT running" in str(ei.value)
            assert "start Docker" in (ei.value.hint or "")

    def test_all_present_does_not_exit(self, fake_proc):
        from sanity_gravity.verbs import check as check_mod

        fake_proc.script("docker compose version", rc=0)
        fake_proc.script("docker info", rc=0)

        with patch.object(check_mod.shutil, "which", return_value="/usr/bin/docker"), \
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
             patch.object(ide_mod, "find_project_containers",
                          return_value=[]), \
             patch.object(ide_mod, "print_error") as err:
            ide_mod.ide_cmd(self._args(name="proj1"))
            err.assert_called_once()
            assert "No running containers" in err.call_args[0][0]

    def test_agent_slug_derived_from_service_tag(self):
        """The agent lookup key is the agent dimension of the discovered
        service tag - not a prefix split of the raw string."""
        from sanity_gravity.verbs import ide as ide_mod

        registry = MagicMock()
        registry.agents = {}

        with patch.object(ide_mod, "get_active_projects",
                          return_value=["proj1"]), \
             patch.object(ide_mod, "find_project_containers",
                          return_value=[{
                              "cid": "c1", "name": "proj1-gc-none-ssh-1",
                              "service": "gc-none-ssh", "running": True,
                          }]), \
             patch("sanity_gravity.core.registry.get_registry",
                   return_value=registry), \
             patch.object(ide_mod, "print_error") as err:
            ide_mod.ide_cmd(self._args(name="proj1"))
            assert "Agent 'gc'" in err.call_args_list[0][0][0]

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

        with patch.object(ide_mod, "get_active_projects",
                          return_value=["proj1"]), \
             patch.object(ide_mod, "find_project_containers",
                          return_value=[{
                              "cid": "c1", "name": "proj1-ag-xfce-kasm-1",
                              "service": "ag-xfce-kasm", "running": True,
                          }]), \
             patch("sanity_gravity.core.registry.get_registry",
                   return_value=registry), \
             patch.object(ide_mod.subprocess, "check_call") as check_call, \
             patch.object(ide_mod, "print_error") as err:
            ide_mod.ide_cmd(self._args(name="proj1"))
            check_call.assert_not_called()
            err.assert_called_once()
            assert "[ide]" in err.call_args[0][0]

    def test_inject_failure_raises(self):
        from sanity_gravity.domain.errors import SanityError
        from sanity_gravity.verbs import ide as ide_mod

        with patch.object(ide_mod, "get_active_projects",
                          return_value=["proj1"]), \
             patch.object(ide_mod, "find_project_containers",
                          return_value=[{
                              "cid": "c1", "name": "proj1-ag-xfce-kasm-1",
                              "service": "ag-xfce-kasm", "running": True,
                          }]), \
             patch.object(ide_mod.subprocess, "check_call",
                          side_effect=subprocess.CalledProcessError(1, "docker cp")), \
             patch.object(ide_mod, "print_header"), \
             patch.object(ide_mod, "print_info"):
            with pytest.raises(SanityError) as ei:
                ide_mod.ide_cmd(self._args(name="proj1"))
            assert ei.value.exit_code == 1
            assert "hot-inject" in str(ei.value)


# ---------------------------------------------------------------------------
# verbs/test_suite.py
# ---------------------------------------------------------------------------


class TestTestSuiteVerb:
    """Cover the pytest-import-failure and exit-code propagation paths."""

    def test_missing_pytest_raises(self):
        # Force the local ``import pytest`` inside ``test_suite`` to fail
        # by making pytest temporarily un-importable.
        from sanity_gravity.domain.errors import SanityError
        from sanity_gravity.verbs import test_suite as ts_mod

        original = sys.modules.pop("pytest", None)
        sys.modules["pytest"] = None  # type: ignore[assignment]
        try:
            with patch.object(ts_mod, "print_header"):
                with pytest.raises(SanityError) as ei:
                    ts_mod.test_suite(argparse.Namespace(target=None))
            assert ei.value.exit_code == 1
            assert "pytest is not installed" in str(ei.value)
            # The exact hint matters: the verb loads hypothesis's plugin
            # explicitly, so anything short of the test extra leaves the
            # user with a failing -p load right after following the hint.
            assert ei.value.hint == 'pip install -e ".[test]"'
        finally:
            if original is not None:
                sys.modules["pytest"] = original
            else:
                sys.modules.pop("pytest", None)

    def test_pytest_nonzero_propagates_exit_code(self):
        from sanity_gravity.domain.errors import SanityError
        from sanity_gravity.verbs import test_suite as ts_mod

        with patch("pytest.main", return_value=2), \
             patch.object(ts_mod, "print_header"):
            with pytest.raises(SanityError) as ei:
                ts_mod.test_suite(argparse.Namespace(target=None))
            assert ei.value.exit_code == 2

    def test_pytest_zero_does_not_exit(self):
        from sanity_gravity.verbs import test_suite as ts_mod

        with patch("pytest.main", return_value=0), \
             patch.object(ts_mod, "print_header"):
            # Must complete without raising.
            ts_mod.test_suite(argparse.Namespace(target="tests/unit"))

    def test_pytest_args_reload_exactly_what_the_suite_uses(self):
        """Pin the argv actually handed to pytest.main: autoload is
        disabled, so every -p is a hard requirement of the environment.
        hypothesis is the suite's one plugin dependency; pytest-timeout
        earns its way back (dep + -p together) the day a timeout marker
        exists."""
        from sanity_gravity.verbs import test_suite as ts_mod

        with patch("pytest.main", return_value=0) as main, \
             patch.object(ts_mod, "print_header"):
            ts_mod.test_suite(argparse.Namespace(target=None))
            assert main.call_args[0][0] == ["-v", "-p", "hypothesispytest"]

            ts_mod.test_suite(argparse.Namespace(target="tests/unit"))
            assert main.call_args[0][0] == [
                "-v", "-p", "hypothesispytest", "tests/unit",
            ]

    def test_plugin_load_failure_is_an_expected_error(self):
        """pytest.main raises (not returns) on a failed -p import; that
        is a predictable environment problem and must cross the CLI
        boundary as a SanityError with the install hint, not as a bare
        ImportError traceback."""
        from sanity_gravity.domain.errors import SanityError
        from sanity_gravity.verbs import test_suite as ts_mod

        boom = ImportError(
            'Error importing plugin "hypothesispytest": No module named '
            "'hypothesis'"
        )
        with patch("pytest.main", side_effect=boom), \
             patch.object(ts_mod, "print_header"):
            with pytest.raises(SanityError) as ei:
                ts_mod.test_suite(argparse.Namespace(target=None))
        assert ei.value.hint == 'pip install -e ".[test]"'
        assert "hypothesispytest" in str(ei.value)
