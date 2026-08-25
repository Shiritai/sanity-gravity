"""Golden master: the generated compose YAML IS the up contract.

``generate_compose_for_tag`` is rendered for one tag per connector
family (kasm / ssh / vnc, covering both desktop and headless variants)
and the full file text is compared byte-for-byte against a checked-in
fixture. This pins every identity-derived string in the file - service
key, image interpolation, volume key, external volume name - so the
Naming migration is provably behavior-preserving.

Discipline (same as test_build_golden.py):
- a fixture diff in a refactor commit is a bug report (refactors must
  be zero-diff);
- a fixture diff in a behavior commit is the review object: regenerate
  with SANITY_UPDATE_GOLDEN=1 and justify every changed line in the
  commit message.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from sanity_gravity.compose.generators import generate_compose_for_tag

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURE_DIR = _REPO_ROOT / "tests" / "fixtures" / "compose"

GOLDEN_TAGS = ("ag-xfce-kasm", "cc-none-ssh", "ag-xfce-vnc")


@pytest.mark.parametrize("tag", GOLDEN_TAGS)
def test_generated_compose_yaml_is_golden(tag, tmp_path, monkeypatch):
    # The generator writes into ./config relative to cwd; isolate it.
    monkeypatch.chdir(tmp_path)
    output_file, service_name = generate_compose_for_tag(tag)

    # The returned path and service name are part of the contract too:
    # hooks/up feeds them straight into docker compose argv.
    assert service_name == tag
    assert output_file == os.path.join("config", f"docker-compose.{tag}.yml")

    text = Path(output_file).read_text(encoding="utf-8")
    fixture = FIXTURE_DIR / f"docker-compose.{tag}.yml"

    if os.environ.get("SANITY_UPDATE_GOLDEN"):
        fixture.parent.mkdir(parents=True, exist_ok=True)
        fixture.write_text(text, encoding="utf-8")
        pytest.skip("golden fixture regenerated; review the diff before committing")

    assert fixture.exists(), (
        "no golden fixture; generate one on KNOWN-GOOD code with "
        "SANITY_UPDATE_GOLDEN=1 pytest tests/unit/test_compose_golden.py"
    )
    assert text == fixture.read_text(encoding="utf-8"), (
        f"generated compose YAML changed for {tag!r}. If this is "
        "deliberate, regenerate with SANITY_UPDATE_GOLDEN=1 and justify "
        "every line of the fixture diff in the commit message."
    )
