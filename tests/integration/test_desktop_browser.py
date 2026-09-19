"""The bundled browser, in a built image.

``tests/unit/test_desktop_browser.py`` reads the Dockerfiles and says the
desktop layers run the shared installer. This says the installer worked:
the binary is there, it starts, and the links that make it *the* browser
of the session point at it.

Read on a plain CLI agent (``cc``) on purpose. The browser used to come
with the ``ag`` agent, so ``ag-xfce-*`` would pass a check like this one
while every other desktop tag failed it; the tag under test here has no
agent-side browser to fall back on.
"""
from __future__ import annotations

import time

import pytest

#: The wrapper the installer plants, and what every browser name links to.
WRAPPER = "/usr/bin/google-chrome-safe"


@pytest.mark.requires_image("cc-xfce-ssh")
class TestDesktopBrowser:
    """The desktop layer's browser on a tag whose agent installs none."""

    def _container(self, clean_container, docker_cli, host_env, image, name):
        container_name = clean_container(name)
        docker_cli.run_container(name=container_name, image=image, env=host_env)
        time.sleep(2)
        return container_name

    def test_the_browser_is_the_browser_of_the_session(
        self, clean_container, docker_cli, host_env, image,
    ):
        """Every way a link reaches a browser has to end at the wrapper:
        ``google-chrome`` for callers that name it, the ``x-www-browser``
        alternative for the xdg-open chain the desktop and the agents use,
        and the menu entry's Exec for a click in the session.

        Nothing here names a package or a file: the entry is
        google-chrome.desktop on amd64 and chromium.desktop on arm64, and
        a hard-coded name is how this check first passed on one arch while
        saying nothing about the other.
        """
        name = self._container(
            clean_container, docker_cli, host_env, image, "sanity-test-desk-browser",
        )

        # One name per `command -v`: dash prints only the first otherwise.
        found = docker_cli.exec(
            name, "sh -c 'command -v google-chrome; command -v xdg-open'",
        )
        assert "/usr/bin/google-chrome" in found.stdout
        assert "/usr/bin/xdg-open" in found.stdout

        resolved = docker_cli.exec(name, "readlink -f /usr/bin/google-chrome")
        assert resolved.stdout.strip() == WRAPPER, (
            f"/usr/bin/google-chrome does not reach the wrapper: {resolved.stdout!r}"
        )

        # The link the chain ends at, read out of the alternatives database
        # rather than off the symlink: a value naming the bare binary is
        # one `update-alternatives --auto` away from losing --no-sandbox.
        for group in ("x-www-browser", "gnome-www-browser"):
            value = docker_cli.exec(
                name,
                f"sh -c 'update-alternatives --query {group} "
                "| sed -n \"s/^Value: //p\"'",
            )
            assert value.stdout.strip() == WRAPPER, (
                f"the {group} alternative is {value.stdout.strip()!r}, not the wrapper"
            )
            link = docker_cli.exec(name, f"readlink -f /usr/bin/{group}")
            assert link.stdout.strip() == WRAPPER, (
                f"/usr/bin/{group} does not resolve to the wrapper: {link.stdout!r}"
            )

        entries = docker_cli.exec(
            name,
            "sh -c 'n=0; "
            "for f in /usr/share/applications/google-chrome*.desktop "
            "/usr/share/applications/chromium*.desktop; do "
            '[ -f "$f" ] || continue; n=$((n+1)); grep ^Exec= "$f"; '
            "done; echo entries=$n'",
        )
        assert "entries=0" not in entries.stdout, (
            "the image ships no browser menu entry at all: "
            f"{entries.stdout!r}"
        )
        execs = [ln for ln in entries.stdout.splitlines() if ln.startswith("Exec=")]
        assert execs, f"the menu entry has no Exec line: {entries.stdout!r}"
        for line in execs:
            assert line.startswith("Exec=/usr/bin/google-chrome"), (
                f"a menu entry starts something other than the wrapper: {line!r}"
            )

    def test_the_browser_starts(
        self, clean_container, docker_cli, host_env, image,
    ):
        """It renders a page with no X server and no network: enough to
        prove the install is complete and the wrapper's --no-sandbox
        reaches it, without making the suite depend on the internet."""
        name = self._container(
            clean_container, docker_cli, host_env, image, "sanity-test-desk-render",
        )

        dom = docker_cli.exec(
            name,
            'sh -c \'google-chrome --headless=new --dump-dom '
            '"data:text/html,<h1>sanity</h1>" 2>/dev/null\'',
        )
        assert "<h1>sanity</h1>" in dom.stdout, (
            f"the bundled browser did not render a page: {dom.stdout[:400]!r}"
        )
