"""The SanityError hierarchy: one root, typed payloads, compat MRO.

The discipline under test: every expected failure carries a user-facing
message, an optional actionable hint, and the exit code the CLI boundary
should end with. Grammar-level errors (TagError & friends) keep
ValueError in their MRO so existing ``except ValueError`` call sites are
untouched during the strangler migration.
"""
from __future__ import annotations

import pytest

from sanity_gravity.domain.errors import CommandError, SanityError


class TestSanityError:
    def test_message_and_defaults(self):
        e = SanityError("m")
        assert str(e) == "m"
        assert e.message == "m"
        assert e.hint is None
        assert e.exit_code == 1

    def test_explicit_exit_code_and_hint(self):
        e = SanityError("m", hint="do X", exit_code=3)
        assert e.exit_code == 3
        assert e.hint == "do X"

    def test_is_plain_exception_not_valueerror(self):
        # The root deliberately does NOT inherit ValueError; only the
        # grammar-level subtypes need the compat MRO.
        assert issubclass(SanityError, Exception)
        assert not issubclass(SanityError, ValueError)


class TestCommandError:
    def test_carries_forensics_and_child_exit_code(self):
        e = CommandError(("docker", "pull", "x"), 7, stderr="boom")
        assert isinstance(e, SanityError)
        assert e.returncode == 7
        assert e.exit_code == 7
        assert e.stderr == "boom"
        assert e.argv == ("docker", "pull", "x")

    def test_zero_returncode_still_exits_nonzero(self):
        # rc 0 treated as a failure must not let the CLI exit 0.
        e = CommandError(("x",), 0)
        assert e.exit_code == 1

    def test_rendered_is_copy_pasteable(self):
        e = CommandError(("docker", "pull", "x"), 1)
        assert e.rendered == "docker pull x"
        e2 = CommandError(("sh", "-c", "a b"), 1)
        assert e2.rendered == "sh -c 'a b'"

    def test_default_message_names_command_and_stderr_head(self):
        e = CommandError(("false",), 2, stderr="first line\nsecond")
        assert "exit 2" in str(e)
        assert "false" in str(e)
        assert "first line" in str(e)
        assert "second" not in str(e)

    def test_shell_string_argv_kept_verbatim(self):
        e = CommandError("a | b", 3)
        assert e.argv == "a | b"
        assert e.rendered == "a | b"


class TestManifestErrorReparent:
    def test_manifest_error_is_both_sanity_and_value_error(self):
        from sanity_gravity.plugins.manifest import ManifestError

        assert issubclass(ManifestError, SanityError)
        assert issubclass(ManifestError, ValueError)
        e = ManifestError("boom", hint="fix the toml")
        assert str(e) == "boom"
        assert e.hint == "fix the toml"
        assert e.exit_code == 1

    def test_manifest_error_still_caught_as_value_error_by_up(self):
        """verbs/up.py catches ValueError around orch.run; a plugin
        manifest error raised inside a hook must keep landing there
        until that call site migrates."""
        from sanity_gravity.plugins.manifest import ManifestError

        with pytest.raises(ValueError):
            raise ManifestError("bad manifest")


class TestTagErrorReparent:
    def test_tag_error_is_sanity_and_value_error(self):
        from sanity_gravity.domain.tags import TagError

        assert issubclass(TagError, SanityError)
        assert issubclass(TagError, ValueError)

    def test_grammar_error_types_share_the_root(self):
        from sanity_gravity.domain.layers import LayerError
        from sanity_gravity.domain.naming import NamingError

        for exc_type in (LayerError, NamingError):
            assert issubclass(exc_type, SanityError)
            assert issubclass(exc_type, ValueError)

    def test_tag_error_still_caught_as_value_error(self):
        """Compat witness: verbs/up.py and friends still say
        ``except ValueError`` around Tag.parse during the migration."""
        from sanity_gravity.domain.tags import Tag, TagError

        with pytest.raises(ValueError):
            Tag.parse("not-a-tag-at-all-way-too-many-parts")
        with pytest.raises(TagError) as ei:
            Tag.parse("nope")
        assert ei.value.exit_code == 1


class TestResolveTagRaisesTagError:
    """core/registry.resolve_tag speaks TagError (still a ValueError:
    the untouched pytest.raises(ValueError) suites are the compat
    proof), and each rejection carries an actionable hint."""

    def test_bad_format_is_tag_error_with_hint(self):
        from sanity_gravity.core.registry import resolve_tag
        from sanity_gravity.domain.tags import TagError

        with pytest.raises(TagError) as ei:
            resolve_tag("nope")
        assert "sanity-cli list" in (ei.value.hint or "")

    def test_unknown_slug_is_tag_error_with_hint(self):
        from sanity_gravity.core.registry import resolve_tag
        from sanity_gravity.domain.tags import TagError

        with pytest.raises(TagError) as ei:
            resolve_tag("zz-xfce-kasm")
        assert "Unknown agent" in str(ei.value)
        assert "sanity-cli list" in (ei.value.hint or "")

    def test_capability_conflict_is_tag_error(self):
        from sanity_gravity.core.registry import resolve_tag
        from sanity_gravity.domain.tags import TagError

        with pytest.raises(TagError, match="requires a GUI desktop"):
            resolve_tag("ag-none-ssh")
