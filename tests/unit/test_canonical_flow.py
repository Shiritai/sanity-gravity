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

from sanity_gravity.core.registry import resolve_tag as real_resolve_tag
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


def test_up_identities_agree_across_modules(monkeypatch, tmp_path, fake_proc):
    """The image pre-flight and the collision probe must be Naming
    renders of the parsed Tag - the exact strings ``ctx.naming`` hands
    to every other module in the same run."""
    # Scripted on command SHAPE, never on the ref: a sink that renders
    # its ref from the raw argv must still get an answer and be caught
    # by the identity assertions below, not die as an unscripted command.
    # The image inspect answers "image exists" so up() does not
    # auto-pull; the collision probe answers "nothing found".
    fake_proc.script("docker image inspect", stdout='[{"Id": "x"}]')
    fake_proc.script("docker ps", stdout="")
    # The kernel's ephemeral-port probe. Success with no stdout is its
    # "could not resolve" answer, so announce prints "?" instead of a
    # port the fake would have had to invent.
    fake_proc.script("docker compose", stdout="")

    # The canonicalizing simulation, installed at the entry parse.
    monkeypatch.setattr(
        up_mod, "resolve_tag", lambda s: real_resolve_tag(s.lower())
    )
    # Not a sink under test; the real one would choke on the raw alias
    # (same disease, different symptom) before the probes even run.
    monkeypatch.setattr(up_mod, "deprecation_warning", lambda s: None)
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

    # 1. No sink may see the raw argv spelling. fake_proc records every
    #    module's proc calls, not just up's, so this covers the whole run.
    blob = "\n".join(fake_proc.commands)
    assert RAW not in blob, f"raw argv leaked into a sink:\n{blob}"

    # 2. The image pre-flight asks about exactly naming.image().
    inspects = [
        c for c in fake_proc.calls
        if "image" in c.text and "inspect" in c.text
    ]
    assert inspects, "up() did not run the image pre-flight"
    assert inspects[0].argv == (
        "docker", "image", "inspect", naming.image(),
    )

    # 3. The collision probe greps for exactly naming.container(),
    #    as argv (nothing here needs a shell).
    probes = fake_proc.calls_matching("name=^")
    assert probes, "up() did not run the collision probe"
    # argv is a str only for run_shell; a tuple proves no shell was used.
    assert isinstance(probes[0].argv, tuple)
    assert probes[0].argv == (
        "docker", "ps", "-a", "-q", "-f", f"name=^{naming.container()}$",
    )


def test_pull_refs_agree_with_naming(monkeypatch, fake_proc):
    """Both refs pull derives for a variant - the GHCR source and the
    local re-tag target - must be Naming renders of the parsed value.

    Same simulation, honestly noted: before the migration pull never
    calls ``Tag.parse`` at all (the patch is inert) and both refs are
    hand-rolled from the raw string, so the canonical expectation fails
    (red). After it, both come from ``Naming`` built on the parsed
    value (green) and cannot disagree with the rest of the system.
    """
    # Shape-only scripting again: a hand-rolled ref must reach the
    # exact-tuple assertions below rather than be rejected as unscripted.
    fake_proc.script("docker pull")
    fake_proc.script("docker tag")

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

    pulls = [c.argv for c in fake_proc.calls_matching("docker pull")]
    tags = [c.argv for c in fake_proc.calls_matching("docker tag")]
    assert pulls == [("docker", "pull", ghcr)]
    assert tags == [("docker", "tag", ghcr, expected.image())]
