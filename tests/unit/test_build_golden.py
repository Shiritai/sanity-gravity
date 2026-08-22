"""Golden master: the docker command sequences ARE the build contract.

Every (case x cache state) below runs through the real kernel (the
BUILD phases with the builtin hooks) with the docker probe faked, and
the resulting command sequence - plus the cache-hit report stream, which
is where one historical copy drifted - is compared byte-for-byte against
a checked-in fixture.

Discipline:
- a fixture diff in a refactor commit is a bug report (refactors must
  be zero-diff);
- a fixture diff in a behavior commit is the review object: regenerate
  with SANITY_UPDATE_GOLDEN=1 and justify every changed line in the
  commit message.

Verb-edge behavior (argv parsing, "all" aliasing, dry-run WouldExecute
printing) is covered by test_dry_run_per_verb.py and test_cli_unit.py;
this file pins the kernel downward.
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from sanity_gravity.core.eventbus import EventBus
from sanity_gravity.core.orchestrator import _BUILD_PHASES, BuildContext, Orchestrator
from sanity_gravity.core.registry import OFFICIAL_TAGS, resolve_tag
from sanity_gravity.core.reporter import Reporter
from sanity_gravity.events import Info
from sanity_gravity.hooks.build import register_builtin_build_hooks
from sanity_gravity.verbs.build import generate_intermediates

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "build_golden.txt"

# Deliberately literal (not derived through the production naming code):
# the fixture is an independent second witness of the naming grammar.
_INTERMEDIATE_IMAGES = frozenset(
    f"sanity-gravity:{name}" for name in generate_intermediates()
)
_FINAL_IMAGES = frozenset(f"sanity-gravity:{t}" for t in OFFICIAL_TAGS)

CACHE_STATES: dict[str, frozenset[str]] = {
    "cold": frozenset(),
    "warm": _INTERMEDIATE_IMAGES,
    "hot": _INTERMEDIATE_IMAGES | _FINAL_IMAGES,
}


def _official_desktops() -> list[str]:
    return sorted({resolve_tag(t).desktop for t in OFFICIAL_TAGS})


def _official_pairs() -> list[tuple[str, str]]:
    return sorted({(resolve_tag(t).agent, resolve_tag(t).desktop) for t in OFFICIAL_TAGS})


def _cases():
    yield "all", dict(targets=["all"])
    for t in OFFICIAL_TAGS:
        yield f"tag:{t}", dict(targets=[t])
    yield "layer:base", dict(targets=[], layer_target="base")
    yield "layer:desktop", dict(targets=[], layer_target="desktop")
    for d in _official_desktops():
        yield f"layer:desktop:{d}", dict(
            targets=[], layer_target="desktop", layer_target_specific=d
        )
    yield "layer:agent", dict(targets=[], layer_target="agent")
    for a, d in _official_pairs():
        yield f"layer:agent:{a}-{d}", dict(
            targets=[], layer_target="agent", layer_target_specific=f"{a}-{d}"
        )
    yield "layer:connector", dict(targets=[], layer_target="connector")
    # Two finals sharing agent+desktop: the closure dedups the common
    # ancestor chain (5 builds, not 2x4) - the multi-target contract.
    yield "multi:ag-xfce-kasm+ag-xfce-vnc", dict(
        targets=["ag-xfce-kasm", "ag-xfce-vnc"]
    )
    # --no-cache disables the probe, so one cache state suffices (see
    # _render_all); these two pin the flag's argv effect.
    yield "all:no-cache", dict(targets=["all"], no_cache=True)
    yield "tag:ag-xfce-kasm:no-cache", dict(targets=["ag-xfce-kasm"], no_cache=True)


class _Events:
    def __init__(self) -> None:
        self.events = []

    def consume(self, event) -> None:
        self.events.append(event)


class _Capture:
    def __init__(self) -> None:
        self.actions = []

    def drain(self, actions, phase=None) -> None:
        self.actions.extend(actions)


def _norm(s: str) -> str:
    # Plugin dockerfile paths resolve absolute via manifest.dockerfile_path;
    # normalize the repo root so the fixture is machine independent.
    return s.replace(str(_REPO_ROOT), "<REPO>")


def _record(case_kw: dict, cached: frozenset[str]) -> list[str]:
    sink = _Events()
    reporter = Reporter(sinks=[sink], run_id="golden")
    bus = EventBus()
    register_builtin_build_hooks(bus)
    ctx = BuildContext(reporter=reporter, dry_run=False, **case_kw)
    ex = _Capture()
    with patch(
        "sanity_gravity.hooks.build._image_exists",
        side_effect=lambda image: image in cached,
    ):
        Orchestrator(bus, reporter, executor=ex).run(_BUILD_PHASES, ctx)
    # The cache-hit stream is part of the contract: the historical drift
    # (one copy skipping the report) is only visible on this channel.
    lines = [
        "! cache-hit " + e.message.split("Cache hit: ", 1)[1]
        for e in sink.events
        if isinstance(e, Info) and "Cache hit: " in e.message
    ]
    lines += [_norm(a.explain()) for a in ex.actions]
    return lines


def _render_all() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for case_key, kw in _cases():
        states = ("cold",) if kw.get("no_cache") else tuple(CACHE_STATES)
        for state in states:
            out[f"{case_key}|{state}"] = _record(dict(kw), CACHE_STATES[state])
    # --list-intermediates is a user-visible string list; pin it too.
    out["list-intermediates|-"] = list(generate_intermediates())
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
    """Enumeration growth must be a deliberate act: a new official tag or
    layer kind red-lights until the fixture is regenerated."""
    expected = _parse(FIXTURE.read_text(encoding="utf-8"))
    missing_tags = {f"tag:{t}|cold" for t in OFFICIAL_TAGS} - set(expected)
    assert not missing_tags, f"golden fixture lacks cases: {sorted(missing_tags)}"
    kinds = {f"layer:{k}|cold" for k in ("base", "desktop", "agent", "connector")}
    assert kinds <= set(expected)
