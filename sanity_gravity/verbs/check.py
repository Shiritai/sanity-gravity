"""``check`` verb: prerequisite (Docker / Compose / daemon) checks."""
from __future__ import annotations

import shutil

from sanity_gravity.cli.io import (
    print_header,
    print_success,
)
from sanity_gravity.core.proc import try_run
from sanity_gravity.domain.errors import SanityError


def _failure_detail(res) -> str:
    """Human detail for a failed probe: stderr head, or the bare rc."""
    head = res.stderr.splitlines()[0] if res.stderr else ""
    return head or f"exit {res.returncode}"


def check_prereqs(args):
    """Check that Docker and Docker Compose are installed and reachable."""
    print_header("Checking Prerequisites")

    if shutil.which("docker"):
        print_success("Docker is installed")
    else:
        raise SanityError(
            "Docker is NOT installed.",
            hint="Please install Docker first: https://docs.docker.com/get-docker/",
        )

    # try_run captures quietly and hands back the rc: probing IS the
    # intent here (the old code abused capture=True as a "quiet" flag
    # and had to catch its own SystemExit).
    res = try_run(("docker", "compose", "version"))
    if not res.ok:
        raise SanityError(
            "Docker Compose is NOT installed or not accessible. "
            f"({_failure_detail(res)})",
            hint="Install the Docker Compose plugin (docker-compose-plugin).",
        )
    print_success("Docker Compose is installed")

    res = try_run(("docker", "info"))
    if not res.ok:
        raise SanityError(
            f"Docker Daemon is NOT running. ({_failure_detail(res)})",
            hint="Please start Docker.",
        )
    print_success("Docker Daemon is running")
