"""Container discovery via compose labels: one docker ps, no probing.

The compose service label IS the canonical tag, so a single labeled
``docker ps`` answers "what is running for this project" without the
historical per-VALID_TAGS ``docker inspect`` probe loop. These tests pin
the contract: one subprocess call, VALID_TAGS ordering for deterministic
first-match, and docker-inspect-compatible running semantics (paused
counts as running, as ``.State.Running`` did).
"""
from unittest.mock import patch

import sanity_gravity.verbs.lifecycle as lc
from sanity_gravity.cli.registry import VALID_TAGS


def _line(cid, name, service, state):
    return f"{cid}|{name}|{service}|{state}"


def test_single_ps_call_results_in_valid_tags_order():
    out = "\n".join([
        _line("c2", "p-cc-none-ssh-1", "cc-none-ssh", "running"),
        _line("c1", "p-ag-xfce-kasm-1", "ag-xfce-kasm", "running"),
    ])
    with patch.object(lc, "run_command", return_value=out) as rc:
        got = lc.find_project_containers("p")

    assert rc.call_count == 1
    cmd = rc.call_args[0][0]
    assert cmd[:3] == ("docker", "ps", "-a")
    assert any("com.docker.compose.project=p" in part for part in cmd)

    assert [r["service"] for r in got] == ["ag-xfce-kasm", "cc-none-ssh"]
    assert got[0] == {
        "cid": "c1", "name": "p-ag-xfce-kasm-1",
        "service": "ag-xfce-kasm", "running": True,
    }
    assert VALID_TAGS.index(got[0]["service"]) < VALID_TAGS.index(got[1]["service"])


def test_default_running_filter_includes_paused_excludes_exited():
    out = "\n".join([
        _line("c1", "p-ag-xfce-kasm-1", "ag-xfce-kasm", "paused"),
        _line("c2", "p-cc-none-ssh-1", "cc-none-ssh", "exited"),
    ])
    with patch.object(lc, "run_command", return_value=out):
        got = lc.find_project_containers("p")
    assert [(r["service"], r["running"]) for r in got] == [("ag-xfce-kasm", True)]


def test_include_stopped_keeps_exited_with_running_false():
    out = _line("c2", "p-cc-none-ssh-1", "cc-none-ssh", "exited")
    with patch.object(lc, "run_command", return_value=out):
        got = lc.find_project_containers("p", include_stopped=True)
    assert [(r["service"], r["running"]) for r in got] == [("cc-none-ssh", False)]


def test_foreign_services_and_malformed_lines_are_ignored():
    out = "\n".join([
        _line("c1", "p-web-1", "web", "running"),      # not a sanity tag
        "garbage line without pipes",
        _line("c2", "p-cc-none-ssh-1", "cc-none-ssh", "running"),
    ])
    with patch.object(lc, "run_command", return_value=out):
        got = lc.find_project_containers("p")
    assert [r["service"] for r in got] == ["cc-none-ssh"]


def test_empty_output_means_no_containers():
    with patch.object(lc, "run_command", return_value=""):
        assert lc.find_project_containers("p") == []
