"""The SSH agent proxy's real systemd round trip.

This changes the host: ``ProxyManager.setup()`` writes
``~/.config/systemd/user/sanity-gravity-proxy.service`` and runs
``systemctl --user`` daemon-reload, enable and restart; ``remove()``
disables the unit and deletes its socket. So it is ``mutates_host`` and
runs only with ``SANITY_DISPOSABLE_HOST=1``. It ends with ``setup()``
so later tests that need the proxy still have it.

The compose policy on top of the proxy state is checked hermetically in
tests/unit/test_git_compose_proxy_policy.py; here it is checked once
against the live proxy.
"""
import io
import os
import sys

import pytest

from sanity_gravity.compose import generators
from sanity_gravity.core.proc import try_run
from sanity_gravity.infra.proxy_manager import ProxyManager

pytestmark = pytest.mark.mutates_host


def _unit_state(pm: ProxyManager, verb: str) -> str:
    return try_run(["systemctl", "--user", verb, pm.service_name]).stdout


def _git_compose(work) -> str | None:
    out = generators.generate_git_compose("testuser")
    return None if out is None else (work / out).read_text()


def test_setup_and_remove_round_trip(tmp_path, monkeypatch):
    # Generated compose goes under tmp_path; no TTY means a missing
    # proxy is reported, never set up from inside the test.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    pm = ProxyManager()
    mount = f"{pm.get_socket_path()}:/tmp/ssh-agent.sock"
    try:
        pm.setup()
        assert os.path.isfile(pm.unit_file_path)
        assert _unit_state(pm, "is-enabled") == "enabled"
        assert _unit_state(pm, "is-active") == "active"
        assert os.path.exists(pm.get_socket_path())
        compose = _git_compose(tmp_path)
        assert compose is not None and mount in compose

        pm.remove()
        assert not os.path.exists(pm.unit_file_path)
        assert _unit_state(pm, "is-active") != "active"
        assert not os.path.exists(pm.get_socket_path())
        compose = _git_compose(tmp_path)
        assert compose is None or "ssh-agent.sock" not in compose
    finally:
        pm.setup()
