"""Tests for username / project-name validation and defence against
shell/sed injection via HOST_USER or --name."""
import pytest


from sanity_gravity.cli.io import (
    validate_project_name,
    validate_username,
)


class TestUsernameValidation:
    @pytest.mark.parametrize("name", [
        "developer",
        "alice",
        "_root",
        "user-1",
        "a",
        "A" * 32,
    ])
    def test_accepts_valid(self, name):
        assert validate_username(name) == name

    @pytest.mark.parametrize("name", [
        "",
        "1leading-digit",
        "-leadingdash",
        "has space",
        "has/slash",
        "'; rm -rf /",
        "a|b",
        "x$y",
        "x`y`",
        "name;drop",
        "A" * 33,
        "unicodeé",
    ])
    def test_rejects_injection(self, name):
        with pytest.raises(ValueError, match="Invalid username"):
            validate_username(name)


class TestProjectNameValidation:
    @pytest.mark.parametrize("name", [
        "sanity-gravity",
        "proj_1",
        "a.b.c",
        "A1",
    ])
    def test_accepts_valid(self, name):
        assert validate_project_name(name) == name

    @pytest.mark.parametrize("name", [
        "",
        "-leadingdash",
        ".dotstart",
        "bad name",
        "has/slash",
        "'; echo pwn",
        "a" * 64,
    ])
    def test_rejects_bad(self, name):
        with pytest.raises(ValueError, match="Invalid project name"):
            validate_project_name(name)
