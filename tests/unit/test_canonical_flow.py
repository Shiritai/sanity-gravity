"""Grammar-simulation red tests: canonical identity reaches every sink.

Technique: patch the entry parser with a CANONICALIZING simulation - a grammar under which "AG-XFCE-SSH"
and "ag-xfce-ssh" are the same identity, the lowercase form canonical.
This is NOT today's grammar (today's parse rejects the former). It is
injected because any sink that derives a name from the raw argv string
instead of the parsed value silently disagrees with the rest of the
system under such a grammar - and that disagreement should be a red
test now, not an incident after a future normalization change.

Written red against the pre-value-flow verbs, green once every verb
derives its names from the parsed Tag: every identity below must agree
with the ``Naming`` renders of the parsed value.
"""
from __future__ import annotations

import argparse

from sanity_gravity.cli.registry import resolve_tag as real_resolve_tag
from sanity_gravity.core.reporter import Reporter
from sanity_gravity.domain.naming import Naming
from sanity_gravity.domain.tags import Tag
from sanity_gravity.effects.executor import build_default_executor
from sanity_gravity.verbs import pull as pull_mod
from sanity_gravity.verbs import up as up_mod

#: What the user typed: an alias only the simulated grammar accepts.
RAW = "AG-XFCE-SSH"
#: What the simulated grammar canonicalizes it to.
CANONICAL = "ag-xfce-ssh"


def _cmd_text(cmd) -> str:
    if isinstance(cmd, (list, tuple)):
        return " ".join(str(p) for p in cmd)
    return str(cmd)


def test_up_identities_agree_across_modules(monkeypatch, tmp_path):
    """The image pre-flight and the collision probe must be Naming
    renders of the parsed Tag - the exact strings ``ctx.naming`` hands
    to every other module in the same run."""
    calls: list = []

    def fake_run_command(cmd, *args, **kwargs):
        calls.append(cmd)
        if kwargs.get("capture"):
            # The image inspect answers "image exists" so up() does not
            # auto-pull; every other probe answers "nothing found".
            return '[{"Id": "x"}]' if "inspect" in _cmd_text(cmd) else ""
        return 0

    # The canonicalizing simulation, installed at the entry parse.
    monkeypatch.setattr(
        up_mod, "resolve_tag", lambda s: real_resolve_tag(s.lower())
    )
    # Not a sink under test; the real one would choke on the raw alias
    # (same disease, different symptom) before the probes even run.
    monkeypatch.setattr(up_mod, "deprecation_warning", lambda s: None)
    monkeypatch.setattr(up_mod, "run_command", fake_run_command)
    monkeypatch.setattr(
        up_mod, "get_uid_gid_user", lambda: (1000, 1000, "dev")
    )
    monkeypatch.setattr(
        up_mod, "generate_compose_for_tag",
        lambda t: (str(tmp_path / f"docker-compose.{t}.yml"), t),
    )
    monkeypatch.setattr(
        up_mod, "generate_git_compose", lambda user, service: None
    )
    monkeypatch.setattr(
        up_mod, "generate_resource_compose", lambda *a: None
    )
    monkeypatch.setattr(up_mod, "sync_config", lambda *a, **kw: None)
    monkeypatch.setattr(up_mod, "is_port_in_use", lambda p: False)
    # args.dry_run must stay False or the probes under test are skipped
    # entirely; a forced dry executor keeps the kernel side effect-free
    # instead.
    monkeypatch.setattr(
        up_mod, "build_default_executor",
        lambda reporter, dry_run=False: build_default_executor(
            reporter, dry_run=True
        ),
    )

    seen: dict = {}
    real_ctx_cls = up_mod.UpContext

    def spy_ctx(**kwargs):
        ctx = real_ctx_cls(**kwargs)
        seen["ctx"] = ctx
        return ctx

    monkeypatch.setattr(up_mod, "UpContext", spy_ctx)

    args = argparse.Namespace(
        variant=RAW,
        name="proj",
        skip_check=True,
        pull=False,
        dry_run=False,
        recreate=False,
        workspace=str(tmp_path / "ws"),
        ssh_port="2222", kasm_port="8444",
        vnc_port="5901", novnc_port="6901",
        password="pw", cpus=None, memory=None, image=None,
        reporter=Reporter(sinks=[], run_id="t", base_dir=tmp_path),
    )
    up_mod.up(args)

    ctx = seen["ctx"]
    assert str(ctx.tag) == CANONICAL  # simulation sanity check
    naming = ctx.naming

    # 1. No sink may see the raw argv spelling.
    blob = "\n".join(_cmd_text(c) for c in calls)
    assert RAW not in blob, f"raw argv leaked into a sink:\n{blob}"

    # 2. The image pre-flight asks about exactly naming.image().
    inspects = [
        c for c in calls
        if "image" in _cmd_text(c) and "inspect" in _cmd_text(c)
    ]
    assert inspects, "up() did not run the image pre-flight"
    assert tuple(inspects[0]) == (
        "docker", "image", "inspect", naming.image(),
    )

    # 3. The collision probe greps for exactly naming.container(),
    #    as argv (nothing here needs a shell).
    probes = [c for c in calls if "name=^" in _cmd_text(c)]
    assert probes, "up() did not run the collision probe"
    assert isinstance(probes[0], tuple)
    assert probes[0] == (
        "docker", "ps", "-a", "-q", "-f", f"name=^{naming.container()}$",
    )


def test_pull_refs_agree_with_naming(monkeypatch):
    """Both refs pull derives for a variant - the GHCR source and the
    local re-tag target - must be Naming renders of the parsed value.

    Same simulation, honestly noted: before the migration pull never
    calls ``Tag.parse`` at all (the patch is inert) and both refs are
    hand-rolled from the raw string, so the canonical expectation fails
    (red). After it, both come from ``Naming`` built on the parsed
    value (green) and cannot disagree with the rest of the system.
    """
    calls: list[tuple] = []

    def fake_run(cmd, *a, **kw):
        calls.append(tuple(cmd) if isinstance(cmd, (list, tuple)) else cmd)
        return "" if kw.get("capture") else 0

    monkeypatch.setattr(pull_mod, "run_command", fake_run)
    monkeypatch.setenv("SANITY_GHCR_REPO", "myorg/myrepo")

    real_parse = Tag.parse.__func__
    monkeypatch.setattr(
        Tag, "parse",
        classmethod(lambda cls, s: real_parse(cls, s.lower())),
    )

    args = argparse.Namespace(variant=[RAW], tag="v9.9.9")
    pull_mod.pull(args)

    expected = Naming(Tag.parse(RAW))  # canonical under the simulation
    ghcr = expected.ghcr("myorg/myrepo", "v9.9.9")

    pulls = [c for c in calls if c[:2] == ("docker", "pull")]
    tags = [c for c in calls if c[:2] == ("docker", "tag")]
    assert pulls == [("docker", "pull", ghcr)]
    assert tags == [("docker", "tag", ghcr, expected.image())]
