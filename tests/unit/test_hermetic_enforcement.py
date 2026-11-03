"""Black-box tests for the hermetic-test enforcement in tests/hermetic.py.

Each case runs a miniature pytest session (pytester, in this process)
against the real tests/conftest.py source and asserts on outcomes and
report text. The inner tests only ever reach the docker/systemctl stubs
or a PermissionError, never the real programs: the audit hook blocks
in-process execs, and the stub dir is first on PATH for child processes.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

pytest_plugins = ["pytester"]

_CONFTEST_UNDER_TEST = (
    Path(__file__).resolve().parent.parent / "conftest.py"
).read_text()

# The opt-out cases declare docker and image preconditions; answer the
# probes here so no inner test ever runs the real docker.
_DOCKER_PRESENT = """

def _docker_available():
    return True


def _image_exists(image):
    return True
"""


def _run(pytester, body: str):
    pytester.makeconftest(_CONFTEST_UNDER_TEST + _DOCKER_PRESENT)
    pytester.makepyfile(body)
    return pytester.runpytest()


def test_blocked_exec_fails_even_when_the_error_is_swallowed(pytester):
    # Each inner test swallows the OSError the way core.proc.try_run and
    # proxy_manager do, so only the teardown record can fail them.
    result = _run(pytester, """
import os
import subprocess


def _quietly(run):
    try:
        run()
    except OSError:
        pass


def test_argv():
    _quietly(lambda: subprocess.run(["docker", "ps"]))


def test_shell_string():
    _quietly(lambda: subprocess.run("true && docker ps -a", shell=True))


def test_os_system():
    _quietly(lambda: os.system("FOO=1 systemctl --user daemon-reload"))


def test_bash_c_with_options():
    _quietly(lambda: subprocess.run(
        ["bash", "-o", "pipefail", "-c", "echo x | sh -c 'docker info'"]))
""")
    result.assert_outcomes(passed=4, errors=4)
    # The argv exec is the audit hook's; the shell ones reach the stubs.
    result.stdout.fnmatch_lines_random([
        "*  exec docker ps",
        "*child exec docker ps -a",
        "*child exec systemctl --user daemon-reload",
        "*child exec docker info",
    ])


def test_write_under_a_fake_home_fails_even_when_swallowed(pytester):
    # pytester points HOME at its project dir, which is outside the
    # inner session's basetemp. The parent dirs do not exist, so the
    # open fails and the product-style code swallows it; the attempt is
    # still recorded.
    result = _run(pytester, """
import os


def _append_event(path):
    try:
        with open(path, "a") as fp:
            fp.write("{}\\n")
    except OSError:
        pass


def test_records_a_run():
    target = os.path.expanduser("~/.cache/sanity-gravity/runs/t/actions.jsonl")
    _append_event(target)
    assert not os.path.exists(target)
""")
    result.assert_outcomes(passed=1, errors=1)
    result.stdout.fnmatch_lines([
        "*hermetic test touched the host:",
        f"*write {pytester.path}/.cache/sanity-gravity/runs/t/actions.jsonl",
    ])


def test_child_process_docker_is_caught_by_the_stub(pytester):
    # The hook sees only `sh run.sh`; the docker call happens two
    # processes down and reaches the stub on PATH.
    result = _run(pytester, """
import subprocess


def test_runs_a_script(tmp_path):
    script = tmp_path / "run.sh"
    script.write_text("sh -c 'docker ps'\\n")
    res = subprocess.run(["sh", str(script)], capture_output=True, text=True)
    assert res.returncode != 0
    assert "not available in a hermetic test" in res.stderr
""")
    result.assert_outcomes(passed=1, errors=1)
    result.stdout.fnmatch_lines(["*child exec docker ps"])


def test_opt_out_markers_are_not_checked(pytester, monkeypatch):
    # cwd is the pytester project dir, outside the inner basetemp: the
    # same write fails a hermetic test (see the fake HOME case).
    monkeypatch.setenv("SANITY_DISPOSABLE_HOST", "1")
    result = _run(pytester, """
import pytest


@pytest.mark.requires_docker
def test_docker():
    open("docker.txt", "w").close()


@pytest.mark.requires_image("ag-xfce-kasm")
def test_image():
    open("image.txt", "w").close()


@pytest.mark.mutates_host
def test_host():
    open("host.txt", "w").close()
""")
    result.assert_outcomes(passed=3)


def test_temp_writes_and_unrelated_words_pass(pytester):
    result = _run(pytester, """
import subprocess
import tempfile


def test_temp_dirs(tmp_path):
    (tmp_path / "out.yml").write_text("x")
    with tempfile.TemporaryDirectory() as d, open(f"{d}/f", "w") as fp:
        fp.write("x")
    with tempfile.NamedTemporaryFile("w") as fp:
        fp.write("x")


def test_docker_as_an_argument_is_not_a_docker_call():
    subprocess.run(["echo", "docker", "systemctl"], check=True)
    subprocess.run("echo docker; printf '%s' 'a; docker'", shell=True, check=True)
""")
    result.assert_outcomes(passed=2)


def test_a_session_cut_short_restores_path_and_tempfile(pytester):
    # pytest.exit skips the inner teardown hook; mutmut keeps running in
    # the same process after pytest.main(), so nothing may stay behind.
    path, tempdir = os.environ["PATH"], tempfile.tempdir
    result = _run(pytester, """
import pytest


def test_stops_the_session():
    pytest.exit("stop")
""")
    assert result.ret == pytest.ExitCode.INTERRUPTED
    assert os.environ["PATH"] == path
    assert tempfile.tempdir == tempdir
