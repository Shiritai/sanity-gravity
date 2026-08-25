"""Black-box tests for the requires_image precondition policy.

The marker policy in tests/conftest.py is test infrastructure - the
tests' tests - so it cannot be trusted to eyeballs. Each case runs a
miniature pytest session (pytester) against the real conftest source
with the docker probes stubbed, and asserts on outcomes and report
text: the exact surface a developer or CI run sees.
"""
from __future__ import annotations

from pathlib import Path

pytest_plugins = ["pytester"]

_CONFTEST_UNDER_TEST = (
    Path(__file__).resolve().parent.parent / "conftest.py"
).read_text()


def _fake_docker(docker_ok: bool, images: tuple[str, ...]) -> str:
    # Rebinding after the real definitions works because
    # pytest_runtest_setup resolves the probes through module globals at
    # call time - the policy logic itself stays fully under test.
    return (
        f"\n\ndef _docker_available():\n    return {docker_ok!r}\n"
        f"\n\ndef _image_exists(image):\n    return image in {tuple(images)!r}\n"
    )


def _project(pytester, body: str, docker_ok: bool = True, images: tuple[str, ...] = ()):
    pytester.makeconftest(_CONFTEST_UNDER_TEST + _fake_docker(docker_ok, images))
    pytester.makepyfile(body)


_OFFICIAL_TAG_TEST = """
import pytest

@pytest.mark.requires_image("ag-xfce-kasm")
def test_boots_the_image(image):
    assert image == "sanity-gravity:ag-xfce-kasm"
"""

# gc is tier=deprecated: no CI build step ever promises its images.
_DEPRECATED_TAG_TEST = """
import pytest

@pytest.mark.requires_image("gc-none-ssh")
def test_boots_the_image(image):
    assert image == "sanity-gravity:gc-none-ssh"
"""


def test_missing_image_skips_with_build_hint(pytester, monkeypatch):
    monkeypatch.delenv("SANITY_REQUIRE_IMAGES", raising=False)
    _project(pytester, _OFFICIAL_TAG_TEST, images=())
    result = pytester.runpytest("-rs")
    result.assert_outcomes(skipped=1)
    result.stdout.fnmatch_lines(
        ["*sanity-gravity:ag-xfce-kasm not built; run ./sanity-cli build ag-xfce-kasm*"]
    )


def test_strict_env_turns_the_skip_into_a_failure(pytester, monkeypatch):
    monkeypatch.setenv("SANITY_REQUIRE_IMAGES", "1")
    _project(pytester, _OFFICIAL_TAG_TEST, images=())
    result = pytester.runpytest()
    # pytest.fail during setup reports as an error, which is the point:
    # nonzero exit, no green suite over a missing official image.
    outcomes = result.parseoutcomes()
    assert outcomes.get("passed", 0) == 0 and outcomes.get("skipped", 0) == 0
    assert outcomes.get("failed", 0) + outcomes.get("errors", 0) == 1
    assert result.ret != 0


def test_strict_env_keeps_skipping_non_official_tags(pytester, monkeypatch):
    """CI's build step never produces deprecated-tier images, so their
    absence under SANITY_REQUIRE_IMAGES=1 is a truthful skip, not a lie."""
    monkeypatch.setenv("SANITY_REQUIRE_IMAGES", "1")
    _project(pytester, _DEPRECATED_TAG_TEST, images=())
    result = pytester.runpytest("-rs")
    result.assert_outcomes(skipped=1)
    result.stdout.fnmatch_lines(
        ["*sanity-gravity:gc-none-ssh not built; run ./sanity-cli build gc-none-ssh*"]
    )


def test_present_image_runs_normally(pytester, monkeypatch):
    monkeypatch.delenv("SANITY_REQUIRE_IMAGES", raising=False)
    _project(pytester, _OFFICIAL_TAG_TEST, images=("sanity-gravity:ag-xfce-kasm",))
    pytester.runpytest().assert_outcomes(passed=1)
