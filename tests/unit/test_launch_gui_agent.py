"""The openbox desktop's GUI-agent detection, run against fixture entries.

``launch-gui-agent`` decides what the openbox session opens. It is built
before the agent layers, so it cannot know at build time which agent is
installed and resolves that at runtime by scanning the installed
``.desktop`` entries. Until now nothing exercised it: the only evidence
it worked was that a kasm session came up with a window in it, which
means a silent non-match reads as "the terminal starter, as intended"
rather than as a bug. That is exactly what the Antigravity 2.x rename
would have caused - the program is ``antigravity-ide`` now, and the bare
name ``antigravity`` belongs to the separate, editor-less "Antigravity
2.0" app.

The script is run for real against directories of entry files, one case
per shape the image can present. The only edit is the applications
directory, substituted the way ``tests/integration/test_gravity_cli.py``
substitutes gravity-cli's install paths - so what runs here is the
shipped text, not a paraphrase of it.
"""
from __future__ import annotations

import stat
import subprocess

import pytest

from tests.support import REPO_ROOT

_SCRIPT = (
    REPO_ROOT / "plugins" / "desktops" / "openbox"
    / "rootfs" / "usr" / "local" / "bin" / "launch-gui-agent"
)

#: The directory the shipped script globs. Replaced with the fixture
#: directory so the real control flow runs over fixture entries.
_APPLICATIONS = "/usr/share/applications"

# The entries the image can hold, as the layers write them.
#
# AG_MENU and AG_HANDLER are both ours: the tarball ships no .desktop at
# all. The handler sorts ahead of the menu entry in the glob -
# "antigravity-ide-" < "antigravity-ide." - which is why the NoDisplay
# skip is load-bearing rather than tidy.
AG_MENU = """\
[Desktop Entry]
Type=Application
Name=Antigravity IDE
Exec=/usr/share/antigravity-ide/antigravity-ide %F
StartupWMClass=antigravity-ide
"""

AG_HANDLER = """\
[Desktop Entry]
Type=Application
Name=Antigravity IDE - URL Handler
NoDisplay=true
Exec=/usr/share/antigravity-ide/antigravity-ide --open-url %U
MimeType=x-scheme-handler/antigravity-ide;
"""

OCD_MENU = """\
[Desktop Entry]
Type=Application
Name=OpenCode Desktop
Exec=/opt/OpenCode/ai.opencode.desktop --no-sandbox --disable-dev-shm-usage %U
"""

CLI_AGENT = """\
[Desktop Entry]
Type=Application
Name=Antigravity CLI
Terminal=true
Exec=agy
"""

STARTER = """\
[Desktop Entry]
Type=Application
Name=Agent Starter
Terminal=true
Exec=/usr/local/bin/agent-starter
"""

#: The 2.0 hub app: upstream's ``antigravity``, an agent surface with no
#: editor in it. Starting it in place of the IDE would leave the session
#: without the thing ``ag`` exists to provide, so the bare name must not
#: match any more.
HUB_MENU = """\
[Desktop Entry]
Type=Application
Name=Antigravity
Exec=/opt/antigravity/antigravity %U
"""

NO_EXEC = """\
[Desktop Entry]
Type=Application
Name=Broken Entry
"""


@pytest.fixture(scope="module")
def script() -> str:
    """The shipped script's text; each case substitutes its own
    applications directory into a copy."""
    return _SCRIPT.read_text(encoding="utf-8")


def _run(script_text: str, tmp_path, entries: dict[str, str]):
    """Run the script over ``entries``, returning the completed process."""
    apps = tmp_path / "applications"
    apps.mkdir()
    for name, body in entries.items():
        (apps / name).write_text(body, encoding="utf-8")

    path = tmp_path / "launch-gui-agent"
    path.write_text(script_text.replace(_APPLICATIONS, str(apps)), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return subprocess.run(
        [str(path)], capture_output=True, text=True, check=False,
    )


def test_the_shipped_script_is_executable():
    """``launch-gui-agent`` is exec'd by the openbox autostart and by
    agent-starter; a 0644 file in the checkout is a dead session."""
    assert _SCRIPT.stat().st_mode & stat.S_IEXEC, (
        f"{_SCRIPT.relative_to(REPO_ROOT)} is not executable"
    )


def test_the_antigravity_ide_entry_resolves(script, tmp_path):
    """ag 2.x: the program is ``antigravity-ide``. This is the case the
    1.x match list did not cover, and its failure mode was an openbox
    session that quietly opened a terminal instead of the IDE."""
    r = _run(script, tmp_path, {"antigravity-ide.desktop": AG_MENU})
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "/usr/share/antigravity-ide/antigravity-ide"


def test_the_url_handler_is_not_the_way_in(script, tmp_path):
    """Our handler entry execs the same program with ``--open-url``, and
    it sorts first. Picked up, the session would open a window asking the
    IDE to handle the empty string."""
    r = _run(script, tmp_path, {
        "antigravity-ide-url-handler.desktop": AG_HANDLER,
        "antigravity-ide.desktop": AG_MENU,
    })
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "/usr/share/antigravity-ide/antigravity-ide"


def test_a_handler_alone_resolves_nothing(script, tmp_path):
    """No menu entry means no GUI agent, even though a matching program
    name is present in the directory."""
    r = _run(script, tmp_path, {"antigravity-ide-url-handler.desktop": AG_HANDLER})
    assert r.returncode == 1
    assert r.stdout.strip() == ""


def test_the_opencode_desktop_entry_resolves_without_field_codes(script, tmp_path):
    """The other GUI agent. ``%U`` has to go: the command is exec'd
    directly, so a surviving field code would arrive as a literal
    argument - and the trailing space it leaves has to go with it."""
    r = _run(script, tmp_path, {"ai.opencode.desktop.desktop": OCD_MENU})
    assert r.returncode == 0, r.stderr
    assert r.stdout == (
        "/opt/OpenCode/ai.opencode.desktop --no-sandbox --disable-dev-shm-usage\n"
    )


def test_a_cli_agent_entry_resolves_nothing(script, tmp_path):
    """agy and the starter are terminal flows: matching either would put
    a TUI where the session expects a window, and agent-starter would
    then exec itself."""
    r = _run(script, tmp_path, {
        "antigravity-cli.desktop": CLI_AGENT,
        "sg-agent-starter.desktop": STARTER,
    })
    assert r.returncode == 1
    assert r.stdout.strip() == ""


def test_the_bare_antigravity_name_no_longer_matches(script, tmp_path):
    """``antigravity`` is the 2.0 hub app in the 2.x world - an agent
    surface with no editor. ``ag`` installs the IDE, and the compat
    command ``/usr/bin/antigravity`` it keeps for shells is named by no
    entry, so the bare program name is not evidence of an IDE."""
    r = _run(script, tmp_path, {"antigravity.desktop": HUB_MENU})
    assert r.returncode == 1
    assert r.stdout.strip() == ""


def test_an_entry_without_an_exec_line_is_skipped(script, tmp_path):
    """A malformed entry must not end the scan: the IDE's own entry may
    sort after it."""
    r = _run(script, tmp_path, {
        "0-broken.desktop": NO_EXEC,
        "antigravity-ide.desktop": AG_MENU,
    })
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "/usr/share/antigravity-ide/antigravity-ide"


def test_an_empty_applications_directory_resolves_nothing(script, tmp_path):
    """A CLI-only image. Callers read exit 1 as "fall back to the
    terminal flow", so this is the normal path for most tags."""
    r = _run(script, tmp_path, {})
    assert r.returncode == 1
    assert r.stdout.strip() == ""


def test_the_match_list_is_program_names_only(script):
    """The rule the script documents: the base name of the program the
    entry execs, never the file name and never the directory. A vendor
    that moves its install prefix must not break detection, and a vendor
    that renames the program must."""
    text = _SCRIPT.read_text(encoding="utf-8")
    assert "ai.opencode.desktop|antigravity-ide)" in text, (
        "the match list no longer names exactly the two GUI agent "
        "programs the agent layers install"
    )
