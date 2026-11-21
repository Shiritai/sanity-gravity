"""Golden master: the docker command sequences ARE the build contract.

Every case below runs through the real kernel (the BUILD phases with
the builtin hooks), and the resulting command sequence is compared
byte-for-byte against a checked-in fixture. There is no cache state to
vary: the plan never consults the local image store, so one recording
per case is the whole contract.

Discipline:
- a fixture diff in a refactor commit is a bug report (refactors must
  be zero-diff);
- a fixture diff in a behavior commit is the review object: regenerate
  with SANITY_UPDATE_GOLDEN=1 and justify every changed line in the
  commit message.

Verb-edge behavior (argv parsing, "all" aliasing, dry-run WouldExecute
printing) is covered by the stacked series' verb suites; this file pins
the kernel downward.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from sanity_gravity.core.eventbus import EventBus
from sanity_gravity.core.orchestrator import _BUILD_PHASES, BuildContext, Orchestrator
from sanity_gravity.core.registry import OFFICIAL_TAGS
from sanity_gravity.core.reporter import Reporter
from sanity_gravity.hooks.build import register_builtin_build_hooks
from sanity_gravity.verbs.build import generate_intermediates

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "build_golden.txt"

# Non-default bases are community tier, so OFFICIAL_TAGS never reaches
# them: one headless and one desktop chain pin the debian build path.
_OTHER_BASE_TAGS = ("cc-none-ssh-debian", "cc-xfce-kasm-debian")


def _cases():
    yield "all", dict(targets=["all"])
    for t in OFFICIAL_TAGS:
        yield f"tag:{t}", dict(targets=[t])
    for t in _OTHER_BASE_TAGS:
        yield f"tag:{t}", dict(targets=[t])
    # Two finals sharing agent+desktop: the closure dedups the common
    # ancestor chain (5 builds, not 2x4) - the multi-target contract.
    yield "multi:ag-xfce-kasm+ag-xfce-vnc", dict(
        targets=["ag-xfce-kasm", "ag-xfce-vnc"]
    )
    # These two pin the --no-cache flag's argv effect.
    yield "all:no-cache", dict(targets=["all"], no_cache=True)
    yield "tag:ag-xfce-kasm:no-cache", dict(targets=["ag-xfce-kasm"], no_cache=True)


class _Capture:
    """Executor stand-in recording enqueued actions verbatim."""

    def __init__(self) -> None:
        self.actions: list = []

    def drain(self, actions, phase=None) -> None:
        self.actions.extend(actions)


def _norm(s: str) -> str:
    # Plugin dockerfile paths resolve absolute via manifest.dockerfile_path;
    # normalize the repo root so the fixture is machine independent.
    return s.replace(str(_REPO_ROOT), "<REPO>")


def _record(case_kw: dict) -> list[str]:
    reporter = Reporter(sinks=[], run_id="golden")
    bus = EventBus()
    register_builtin_build_hooks(bus)
    ctx = BuildContext(reporter=reporter, dry_run=False, **case_kw)
    ex = _Capture()
    Orchestrator(bus, reporter, executor=ex).run(_BUILD_PHASES, ctx)
    return [_norm(a.explain()) for a in ex.actions]


def _render_all() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for case_key, kw in _cases():
        out[case_key] = _record(dict(kw))
    # --list-intermediates is a user-visible string list; pin it too.
    out["list-intermediates"] = list(generate_intermediates())
    return out


def _serialise(recorded: dict[str, list[str]]) -> str:
    blocks = [
        f"# case={key}\n" + "\n".join(recorded[key]) for key in sorted(recorded)
    ]
    return "\n\n".join(blocks) + "\n"


def _parse(text: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    key = None
    for line in text.splitlines():
        if line.startswith("# case="):
            key = line[len("# case="):]
            out[key] = []
        elif line.strip():
            assert key is not None, f"fixture line before any case header: {line!r}"
            out[key].append(line)
    return out


def test_build_command_sequences_are_golden():
    recorded = _render_all()
    if os.environ.get("SANITY_UPDATE_GOLDEN"):
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(_serialise(recorded), encoding="utf-8")
        pytest.skip("golden fixture regenerated; review the diff before committing")
    assert FIXTURE.exists(), (
        "no golden fixture; generate one on KNOWN-GOOD code with "
        "SANITY_UPDATE_GOLDEN=1 pytest tests/unit/test_build_golden.py"
    )
    expected = _parse(FIXTURE.read_text(encoding="utf-8"))
    for key in sorted(set(expected) | set(recorded)):
        assert recorded.get(key) == expected.get(key), (
            f"docker sequence changed for {key!r}. If this is deliberate, "
            "regenerate with SANITY_UPDATE_GOLDEN=1 and justify every line "
            "of the fixture diff in the commit message."
        )


def test_golden_covers_the_whole_matrix():
    """Enumeration growth must be a deliberate act: a new official tag
    red-lights until the fixture is regenerated."""
    expected = _parse(FIXTURE.read_text(encoding="utf-8"))
    missing_tags = {f"tag:{t}" for t in OFFICIAL_TAGS} - set(expected)
    assert not missing_tags, f"golden fixture lacks cases: {sorted(missing_tags)}"
