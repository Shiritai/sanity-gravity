"""Contract of the two input validators in ``sanity_gravity.cli.io``.

``validate_username`` and ``validate_project_name`` are the last line of
defence between user input and shell / sed / docker-compose contexts.
Each is a single anchored regex, so each gets a single table: the
accepted set, the rejected set, and the non-string boundary.

Merged from the former ``test_input_validation.py`` /
``test_io_validation.py``. Despite covering the same two one-line
functions, those files had *opposite* blind spots -- each held cases the
other could not kill:

  - project body class drops '_'       -> only ``proj_1`` goes red
  - username body widened to \\w        -> only ``unicode-e-acute`` does
  - project head restricted to alpha   -> only ``0digit`` does
  - username body gains '.'            -> only ``user.name`` does

so the union below is the lossless merge; neither file alone was.
Every row is annotated with the regex property it owns, and rows whose
property was already owned by a sibling row were dropped in the merge.
"""
from __future__ import annotations

import pytest

from sanity_gravity.cli.io import validate_project_name, validate_username

# --- validate_username: ^[a-zA-Z_][a-zA-Z0-9_-]{0,31}$ -------------------

USERNAME_VALID = [
    "developer",        # plain lowercase alpha
    "_root",            # '_' is in the head class
    "user-1",           # '-' and a digit in the body
    "user-123",         # multi-digit body run
    "u_v",              # '_' in the body
    "a",                # minimum length, alpha head
    "_",                # minimum length, '_' head (body may be empty)
    "Z9",               # uppercase head + digit body
    "A" * 32,           # length boundary, upper
    "u" * 32,           # length boundary, lower
]

USERNAME_INVALID = [
    "",                 # empty
    "1leading-digit",   # head class excludes digits
    "9user",            # ditto, single-digit head
    "-leadingdash",     # head excludes '-' even though the body allows it
    "has space",        # space
    "user name",        # space behind a valid head
    "has/slash",        # '/'
    "user/name",        # '/' behind a valid head
    "a|b",              # shell pipe
    "x$y",              # shell expansion
    "x`y`",             # command substitution
    "name;drop",        # command separator
    "user;rm",          # ditto
    "user@host",        # '@'
    "user.name",        # '.' must NOT leak into the username body
    "unicodeé",    # body is ASCII-only, not \\w
    "A" * 33,           # one over the length boundary, upper
    "u" * 33,           # one over the length boundary, lower
]

# --- validate_project_name: ^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}$ ------------

PROJECT_VALID = [
    "sanity-gravity",   # '-' in the body
    "proj_1",           # '_' in the body
    "a.b.c",            # repeated '.' in the body
    "my.project",       # single '.'
    "A1",               # uppercase head + digit
    "p1",               # lowercase head + digit
    "Z",                # minimum length (body may be empty)
    "0digit",           # head DOES admit a digit, unlike usernames
    "a" * 63,           # length boundary
]

PROJECT_INVALID = [
    "",                 # empty
    "-leadingdash",     # head excludes '-' even though the body allows it
    ".dotstart",        # ditto for '.'
    "_underscore",      # ditto for '_'
    "bad name",         # space
    "my project",       # space behind a valid head
    "has/slash",        # '/'
    "my/project",       # '/' behind a valid head
    "my$project",       # shell expansion
    "a" * 64,           # one over the length boundary
]

#: (validator, message prefix) - the two surfaces share every contract
#: below apart from their alphabets.
VALIDATORS = [
    (validate_username, "Invalid username"),
    (validate_project_name, "Invalid project name"),
]
VALIDATOR_IDS = ["username", "project_name"]


class TestValidateUsername:
    @pytest.mark.parametrize("name", USERNAME_VALID)
    def test_accepts_valid(self, name):
        assert validate_username(name) == name

    @pytest.mark.parametrize("name", USERNAME_INVALID)
    def test_rejects_invalid(self, name):
        with pytest.raises(ValueError, match="Invalid username"):
            validate_username(name)


class TestValidateProjectName:
    @pytest.mark.parametrize("name", PROJECT_VALID)
    def test_accepts_valid(self, name):
        assert validate_project_name(name) == name

    @pytest.mark.parametrize("name", PROJECT_INVALID)
    def test_rejects_invalid(self, name):
        with pytest.raises(ValueError, match="Invalid project name"):
            validate_project_name(name)


class TestRejectionContract:
    """What the caller may rely on when a name is refused.

    ``None`` is the one input where the ``if not name`` guard is
    load-bearing rather than belt-and-braces. For ``""`` the guard is
    redundant: both patterns are anchored and require a head character,
    so ``match("")`` is already None -- delete the guard and the empty
    string is still refused with the same ValueError. No test on ``""``
    can therefore witness the guard, and this file does not pretend
    otherwise; ``""`` lives in the tables above as a behaviour pin.

    For ``None`` the guard is the whole contract:
    ``re.Pattern.match(None)`` raises ``TypeError``, so without the
    guard the documented "raises ValueError" promise is simply false.
    Asserting the *exact* type is what makes that observable -- the
    predecessor of this test accepted ``(ValueError, TypeError)``, which
    both the guarded and the unguarded implementation satisfy, and so
    could never fail in either direction.
    """

    @pytest.mark.parametrize(
        "validator,message", VALIDATORS, ids=VALIDATOR_IDS
    )
    def test_none_raises_value_error_not_type_error(self, validator, message):
        with pytest.raises(ValueError, match=f"{message} 'None'"):
            validator(None)

    @pytest.mark.parametrize(
        "validator,message", VALIDATORS, ids=VALIDATOR_IDS
    )
    def test_message_quotes_the_offending_value(self, validator, message):
        """The message must name the input; an operator debugging a
        rejected --name or HOST_USER has nothing else to go on. The
        tables above only match the prefix, so this is the sole guard
        on the interpolation."""
        with pytest.raises(ValueError, match=f"{message} 'bad name'"):
            validator("bad name")
