"""``gravity-cli``: the container-side installer for the Antigravity IDE.

The same script installs the IDE at build time (``ide install`` with the
Dockerfile's pin) and replaces it inside a running sandbox (``ide
update``, resolving the current build from Google's updater API). One
code path, so the wrapper and the .desktop entries in a built image are
the text asserted here rather than a second copy of it - the old layout
had the wrapper written twice, in the Dockerfile and here, and the two
had already drifted apart.

The download is the only thing faked: ``curl`` serves a fixture tarball
laid out like the real one, and ``dpkg --print-architecture`` answers for
whichever host runs the suite. Everything else runs - tar, jq, openssl,
sha256sum, install - so what is under test is the real extraction, the
real product.json patch and a real sha256 mismatch, not a mock of one.

No image and no daemon: this reads the plugin's rootfs and runs bash.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import tarfile
import textwrap
from pathlib import Path

import pytest

from tests.support import REPO_ROOT

pytestmark = pytest.mark.no_image

GRAVITY_CLI_PATH = (
    REPO_ROOT / "plugins" / "agents" / "ag" / "rootfs"
    / "usr" / "local" / "bin" / "gravity-cli"
)

#: The pin the fixture stands in for. Any version string will do: the
#: installer is told the build directory, not asked to guess it.
FIXTURE_VERSION = "2.5.5"
FIXTURE_BUILD = "4923483625488384"
FIXTURE_BUILD_DIR = f"{FIXTURE_VERSION}-{FIXTURE_BUILD}"

#: Where the real artifact lives. The installer must build exactly this
#: shape, or the pin points at nothing.
DOWNLOAD_BASE = "https://edgedl.me.gvt1.com/edgedl/release2/j0qc3/antigravity/stable"
UPDATER_API = (
    "https://antigravity-ide-auto-updater-974169037036.us-central1.run.app"
)

#: Absolute paths the script writes to, each redirected into the test's
#: own tree. Longest first is not required (none is a prefix of another),
#: but the trailing slash on the last two is: ``/usr/bin`` must not catch
#: ``/usr/local/bin/gravity-cli`` in the help text.
_REDIRECTS = (
    ("/usr/share/antigravity-ide", "share/antigravity-ide"),
    ("/usr/share/applications", "share/applications"),
    ("/usr/share/pixmaps", "share/pixmaps"),
    ("/etc/xdg", "etc/xdg"),
    ("/usr/bin/", "bin/"),
    ("/home/", "home/"),
)

_CERT_DAYS = 400


def _self_signed_cert(path: Path) -> None:
    """A certificate the installer's own expiry report can read.

    Generated rather than committed: a fixture certificate would expire
    on its own schedule and take this test with it, which is the very
    failure this plugin now guards against.
    """
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", os.devnull, "-out", str(path),
            "-days", str(_CERT_DAYS),
            "-subj", "/CN=localhost/O=ENABLES HTTP2/OU=bundled on purpose",
        ],
        check=True, capture_output=True,
    )


def _fixture_tarball(dest_dir: Path) -> tuple[Path, str]:
    """Build a tarball shaped like ``Antigravity IDE.tar.gz``.

    Returns its path and its sha256. The top-level directory name has
    the space the real one has: ``--strip-components=1`` is what keeps
    that space out of every path downstream, and a fixture without it
    would let a regression through.
    """
    root = dest_dir / "Antigravity IDE"
    app = root / "resources" / "app"
    (app / "out").mkdir(parents=True)
    (app / "resources" / "linux").mkdir(parents=True)
    ls_dir = app / "extensions" / "antigravity" / "dist" / "languageServer"
    ls_dir.mkdir(parents=True)
    (root / "bin").mkdir()

    (root / "antigravity-ide").write_text("#!/bin/sh\necho electron \"$@\"\n")
    (root / "antigravity-ide").chmod(0o755)
    (root / "bin" / "antigravity-ide").write_text("#!/bin/sh\nexit 0\n")
    (root / "bin" / "antigravity-ide").chmod(0o755)
    # setuid root, as the real tarball ships it.
    (root / "chrome-sandbox").write_bytes(b"\x7fELF fixture")
    (root / "chrome-sandbox").chmod(0o4755)
    (app / "out" / "cli.js").write_text("// cli\n")
    (app / "resources" / "linux" / "code.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (app / "product.json").write_text(json.dumps({
        "nameLong": "Antigravity IDE",
        "applicationName": "antigravity-ide",
        "urlProtocol": "antigravity-ide",
        "updateUrl": "https://example.com",
        "backupUpdateUrl": "https://example.invalid",
        "quality": "stable",
    }, indent=2) + "\n")
    _self_signed_cert(ls_dir / "cert.pem")

    tarball = dest_dir / "ide.tar.gz"
    with tarfile.open(tarball, "w:gz") as tf:
        tf.add(root, arcname="Antigravity IDE")
    return tarball, hashlib.sha256(tarball.read_bytes()).hexdigest()


def _mock(dir_path: Path, name: str, body: str) -> None:
    path = dir_path / name
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _sandboxed_cli(tmp_path: Path) -> Path:
    """The shipped script with its absolute write targets redirected.

    Substitution rather than a test-only switch inside the script: the
    text that runs here is then the text that runs in the image, down to
    the wrapper body this file compares byte for byte.
    """
    content = GRAVITY_CLI_PATH.read_text(encoding="utf-8")
    # The root check is the one thing the test cannot satisfy.
    content = content.replace('[ "$EUID" -ne 0 ]', "false")
    for absolute, relative in _REDIRECTS:
        target = tmp_path / relative
        if absolute.endswith("/"):
            # A prefix, not a file: the trailing slash carries meaning
            # (``/home/*``, ``/usr/bin/antigravity``) and Path drops it.
            target.mkdir(parents=True, exist_ok=True)
            content = content.replace(absolute, f"{target}/")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            content = content.replace(absolute, str(target))

    out = tmp_path / "gravity-cli"
    out.write_text(content)
    out.chmod(out.stat().st_mode | stat.S_IEXEC)
    return out


def _curl_mock(tarball: Path, api_json: str | None = None) -> str:
    """A curl that answers the two requests the installer makes.

    ``-o <file>`` is the artifact download and gets the fixture bytes;
    everything else is the updater API and goes to stdout.
    """
    api = api_json if api_json is not None else ""
    return textwrap.dedent(f"""\
        #!/bin/bash
        dest=""
        prev=""
        for a in "$@"; do
            if [ "$prev" = "-o" ]; then dest="$a"; fi
            prev="$a"
        done
        printf '%s\\n' "curl $*" >> {tarball.parent}/curl.log
        if [ -n "$dest" ]; then
            cp {tarball} "$dest"
        else
            printf '%s' {api!r}
        fi
        """)


@pytest.fixture
def world(tmp_path):
    """A redirected gravity-cli plus a fixture tarball and its sha256."""
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    tarball, sha = _fixture_tarball(downloads)
    cli = _sandboxed_cli(tmp_path)
    bin_dir = tmp_path / "mockbin"
    bin_dir.mkdir()
    _mock(bin_dir, "dpkg", '#!/bin/bash\necho amd64\n')
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ.get('PATH', '')}")
    return cli, tarball, sha, bin_dir, env


def _run(cli: Path, env: dict, *args: str):
    return subprocess.run(
        ["bash", str(cli), *args], env=env, capture_output=True, text=True,
    )


def _installed(tmp_path: Path) -> Path:
    return tmp_path / "share" / "antigravity-ide"


# -- the pinned install (what the Dockerfile runs) ----------------------


def test_the_pinned_install_lays_out_the_app(world, tmp_path):
    cli, tarball, sha, bin_dir, env = world
    _mock(bin_dir, "curl", _curl_mock(tarball))

    r = _run(cli, env, "ide", "install", FIXTURE_VERSION, FIXTURE_BUILD, sha)
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"

    app = _installed(tmp_path)
    # --strip-components=1 dropped the space-bearing top directory.
    assert (app / "resources" / "app" / "out" / "cli.js").is_file()
    assert not (app / "Antigravity IDE").exists()
    # The vendor binary moved aside so the wrapper can hold its path.
    assert (app / "antigravity-ide-bin").is_file()
    assert (app / "bin" / "antigravity-ide").is_file()
    # An unused setuid root binary does not ship.
    assert stat.S_IMODE((app / "chrome-sandbox").stat().st_mode) == 0o755


def test_the_download_url_is_the_immutable_one(world, tmp_path):
    """Version and build id both in the path, the space encoded, and the
    per-architecture directory the download side spells ``linux-x64``."""
    cli, tarball, sha, bin_dir, env = world
    _mock(bin_dir, "curl", _curl_mock(tarball))

    _run(cli, env, "ide", "install", FIXTURE_VERSION, FIXTURE_BUILD, sha)
    log = (tarball.parent / "curl.log").read_text()
    assert (
        f"{DOWNLOAD_BASE}/{FIXTURE_BUILD_DIR}/linux-x64/Antigravity%20IDE.tar.gz"
        in log
    ), log


def test_a_sha256_mismatch_installs_nothing(world, tmp_path):
    """The pin is the only thing standing between the sandbox and
    whatever the network returned, so a mismatch has to be fatal - and
    has to leave no half-installed tree behind."""
    cli, tarball, _sha, bin_dir, env = world
    _mock(bin_dir, "curl", _curl_mock(tarball))

    r = _run(cli, env, "ide", "install", FIXTURE_VERSION, FIXTURE_BUILD, "0" * 64)
    assert r.returncode != 0
    assert not _installed(tmp_path).exists()


def test_the_installed_build_is_recorded(world, tmp_path):
    """Neither product.json nor the updater API carries the 2.x version
    (both say 1.107.0, the VS Code base), so the build the sandbox is
    running is only knowable if the installer writes it down."""
    cli, tarball, sha, bin_dir, env = world
    _mock(bin_dir, "curl", _curl_mock(tarball))

    _run(cli, env, "ide", "install", FIXTURE_VERSION, FIXTURE_BUILD, sha)
    recorded = (_installed(tmp_path) / ".antigravity-build").read_text().strip()
    assert recorded == FIXTURE_BUILD_DIR


def test_the_update_url_is_removed_from_product_json(world, tmp_path):
    """VS Code's update service reports MissingConfiguration and stays
    off when no URL is configured. That is the layer the sandbox user
    cannot switch back on - and the update that would otherwise fire is
    the one that moves the install onto the separate 2.0 app."""
    cli, tarball, sha, bin_dir, env = world
    _mock(bin_dir, "curl", _curl_mock(tarball))

    _run(cli, env, "ide", "install", FIXTURE_VERSION, FIXTURE_BUILD, sha)
    product = json.loads(
        (_installed(tmp_path) / "resources" / "app" / "product.json").read_text()
    )
    assert "updateUrl" not in product
    assert "backupUpdateUrl" not in product
    # Only those two: the rest of the file is upstream's.
    assert product["applicationName"] == "antigravity-ide"


def test_the_wrapper_is_written_verbatim(world, tmp_path):
    """The three branches, unchanged in shape from the 1.x wrapper: a
    node-mode child runs with no Chromium flags, a ``--type=`` child is a
    Chromium child, everything else is the GUI process.

    ``--no-zygote`` is the correction this migration carries:
    ``--disable-zygote`` is not a Chromium switch (only ``kNoZygote``
    exists in content_switches.cc) and unknown switches are dropped in
    silence, so the old line had never done anything.
    """
    cli, tarball, sha, bin_dir, env = world
    _mock(bin_dir, "curl", _curl_mock(tarball))

    _run(cli, env, "ide", "install", FIXTURE_VERSION, FIXTURE_BUILD, sha)
    app = _installed(tmp_path)
    wrapper = app / "antigravity-ide"
    assert wrapper.read_text() == textwrap.dedent(f"""\
        #!/bin/bash
        # Master wrapper for the Antigravity IDE in the sanity-gravity sandbox.
        # Written by gravity-cli; change it there, not here.

        # 1. Environment Fix for Electron Children
        export ELECTRON_DISABLE_SANDBOX=1

        # 2. Process Type Detection
        IS_GUI_CHILD=0
        for arg in "$@"; do
            if [[ "$arg" == --type=* ]]; then
                IS_GUI_CHILD=1
                break
            fi
        done

        # 3. Execution Logic
        if [ "$ELECTRON_RUN_AS_NODE" = "1" ] && [ "$IS_GUI_CHILD" = "0" ]; then
            # Pure CLI Node mode - NO sandbox flags allowed here
            exec {app}/antigravity-ide-bin "$@"
        fi

        # Everything else is a GUI process or a child process requiring Chromium
        # flags. --no-zygote is the switch Chromium actually defines
        # (content_switches.cc, kNoZygote); the spelling this line used to carry
        # was not a switch at all and was dropped in silence.
        unset ELECTRON_RUN_AS_NODE
        exec {app}/antigravity-ide-bin \\
            --no-sandbox \\
            --disable-dev-shm-usage \\
            --no-zygote \\
            --disable-namespace-sandbox \\
            "$@"
        """)
    assert os.access(wrapper, os.X_OK)


def test_the_path_names_both_the_ide_and_the_compat_alias(world, tmp_path):
    """``antigravity-ide`` is the 2.x program name and the one the
    .desktop entries and the openbox detection use. ``antigravity`` stays
    for shells and scripts that learned the 1.x name - including this
    suite's own ``antigravity --version`` check."""
    cli, tarball, sha, bin_dir, env = world
    _mock(bin_dir, "curl", _curl_mock(tarball))

    _run(cli, env, "ide", "install", FIXTURE_VERSION, FIXTURE_BUILD, sha)
    bin_dir_out = tmp_path / "bin"
    assert (bin_dir_out / "antigravity-ide").resolve() == (
        _installed(tmp_path) / "bin" / "antigravity-ide"
    )
    assert (bin_dir_out / "antigravity").resolve() == (
        _installed(tmp_path) / "bin" / "antigravity-ide"
    )


def test_the_desktop_entries_and_the_scheme_handler_are_installed(world, tmp_path):
    """The tarball ships no .desktop, so both entries are ours. The
    handler is what 2.x sign-in needs: the callback is an
    ``antigravity-ide://oauth-success`` deep link, not a localhost port,
    and with no handler the last step of the login lands nowhere."""
    cli, tarball, sha, bin_dir, env = world
    _mock(bin_dir, "curl", _curl_mock(tarball))

    _run(cli, env, "ide", "install", FIXTURE_VERSION, FIXTURE_BUILD, sha)
    apps = tmp_path / "share" / "applications"
    menu = (apps / "antigravity-ide.desktop").read_text()
    handler = (apps / "antigravity-ide-url-handler.desktop").read_text()

    wrapper = _installed(tmp_path) / "antigravity-ide"
    assert "Name=Antigravity IDE\n" in menu
    # The wrapper, not the PATH command: /usr/bin/antigravity-ide is
    # upstream's CLI shim and re-spawns the app without the sandbox flags.
    assert f"Exec={wrapper} %F\n" in menu
    assert "StartupWMClass=antigravity-ide\n" in menu
    assert "NoDisplay" not in menu

    assert "NoDisplay=true\n" in handler
    assert f"Exec={wrapper} --open-url %U\n" in handler
    assert "MimeType=x-scheme-handler/antigravity-ide;\n" in handler

    assert (tmp_path / "share" / "pixmaps" / "antigravity-ide.png").is_file()


def test_the_scheme_default_is_registered_once(world, tmp_path):
    """Registered, not just declared: xdg-open resolves the scheme
    through mimeapps.list, and a handler nothing points at is a login
    that still fails. Re-running must not append a second line."""
    cli, tarball, sha, bin_dir, env = world
    _mock(bin_dir, "curl", _curl_mock(tarball))

    _run(cli, env, "ide", "install", FIXTURE_VERSION, FIXTURE_BUILD, sha)
    _run(cli, env, "ide", "install", FIXTURE_VERSION, FIXTURE_BUILD, sha)
    mimeapps = (tmp_path / "etc" / "xdg" / "mimeapps.list").read_text()
    assert mimeapps.count(
        "x-scheme-handler/antigravity-ide=antigravity-ide-url-handler.desktop"
    ) == 1, mimeapps
    assert mimeapps.count("[Default Applications]") == 1, mimeapps


def test_an_existing_mimeapps_list_keeps_its_other_entries(world, tmp_path):
    """The desktop layer may have registered the browser there. Writing
    the file wholesale would take that with it."""
    cli, tarball, sha, bin_dir, env = world
    _mock(bin_dir, "curl", _curl_mock(tarball))
    mimeapps = tmp_path / "etc" / "xdg" / "mimeapps.list"
    mimeapps.parent.mkdir(parents=True, exist_ok=True)
    mimeapps.write_text(
        "[Default Applications]\n"
        "x-scheme-handler/https=google-chrome.desktop\n"
    )

    _run(cli, env, "ide", "install", FIXTURE_VERSION, FIXTURE_BUILD, sha)
    text = mimeapps.read_text()
    assert "x-scheme-handler/https=google-chrome.desktop" in text
    assert "x-scheme-handler/antigravity-ide=antigravity-ide-url-handler.desktop" in text


def test_the_install_reports_the_certificate_dates(world, tmp_path):
    """The one fact a maintainer has to be able to read off a build log
    (#42): when the bundled language-server certificate dies."""
    cli, tarball, sha, bin_dir, env = world
    _mock(bin_dir, "curl", _curl_mock(tarball))

    r = _run(cli, env, "ide", "install", FIXTURE_VERSION, FIXTURE_BUILD, sha)
    assert "notAfter=" in r.stdout, r.stdout


def test_a_missing_file_in_the_tarball_fails_the_install(world, tmp_path):
    """Upstream re-arranging the layout must be a red build, not a
    sandbox whose IDE opens to nothing. cert.pem going away would even
    be good news - and still has to be noticed."""
    cli, tarball, _sha, bin_dir, env = world
    stripped = tarball.parent / "stripped.tar.gz"
    with tarfile.open(tarball) as src, tarfile.open(stripped, "w:gz") as dst:
        for member in src.getmembers():
            if member.name.endswith("out/cli.js"):
                continue
            extracted = src.extractfile(member) if member.isfile() else None
            dst.addfile(member, extracted)
    sha = hashlib.sha256(stripped.read_bytes()).hexdigest()
    _mock(bin_dir, "curl", _curl_mock(stripped))

    r = _run(cli, env, "ide", "install", FIXTURE_VERSION, FIXTURE_BUILD, sha)
    assert r.returncode != 0
    assert "cli.js" in r.stdout + r.stderr


def test_the_pinned_install_rejects_a_wrong_argument_count(world, tmp_path):
    cli, _tarball, _sha, _bin_dir, env = world
    r = _run(cli, env, "ide", "install", FIXTURE_VERSION)
    assert r.returncode != 0
    assert "usage" in (r.stdout + r.stderr).lower()


# -- the update path (what `./sanity-cli ide update` runs) --------------


def _api_payload(sha: str, build_dir: str = FIXTURE_BUILD_DIR) -> str:
    """The updater API's answer, in its real shape - note the literal
    space in the URL, which the installer has to encode."""
    return json.dumps({
        "productVersion": "1.107.0",
        "sha256hash": sha,
        "url": f"{DOWNLOAD_BASE}/{build_dir}/linux-x64/Antigravity IDE.tar.gz",
    })


def test_update_installs_the_build_the_updater_api_names(world, tmp_path):
    """The sha256 comes from Google, so the pin is cross-checked against
    upstream rather than only against ourselves. The apt route it
    replaces could not verify anything: it trusted a repository that had
    not moved in five months."""
    cli, tarball, sha, bin_dir, env = world
    _mock(bin_dir, "curl", _curl_mock(tarball, _api_payload(sha)))

    r = _run(cli, env, "ide", "update")
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    assert "IDE update completed successfully" in r.stdout
    log = (tarball.parent / "curl.log").read_text()
    assert f"{UPDATER_API}/api/update/linux-x64/stable/latest" in log, log
    assert (_installed(tmp_path) / "antigravity-ide-bin").is_file()


def test_update_refuses_a_download_url_off_the_official_path(world, tmp_path):
    """The API hands over a URL; taking it on trust would make the whole
    verification circular. Anything but the immutable path on the
    official host is refused before a byte is fetched."""
    cli, tarball, sha, bin_dir, env = world
    payload = json.dumps({
        "sha256hash": sha,
        "url": "https://example.invalid/antigravity/Antigravity IDE.tar.gz",
    })
    _mock(bin_dir, "curl", _curl_mock(tarball, payload))

    r = _run(cli, env, "ide", "update")
    assert r.returncode != 0
    assert "unexpected download URL" in r.stdout + r.stderr
    assert not _installed(tmp_path).exists()


def test_update_refuses_a_payload_with_no_usable_sha256(world, tmp_path):
    cli, tarball, _sha, bin_dir, env = world
    _mock(bin_dir, "curl", _curl_mock(tarball, _api_payload("not-a-hash")))

    r = _run(cli, env, "ide", "update")
    assert r.returncode != 0
    assert "sha256" in (r.stdout + r.stderr).lower()
    assert not _installed(tmp_path).exists()


def test_update_replaces_an_existing_install(world, tmp_path):
    """``ide update`` runs against a live sandbox, so it has to be
    idempotent and has to leave nothing of the previous tree behind."""
    cli, tarball, sha, bin_dir, env = world
    _mock(bin_dir, "curl", _curl_mock(tarball, _api_payload(sha)))

    assert _run(cli, env, "ide", "update").returncode == 0
    app = _installed(tmp_path)
    (app / "stale-file").write_text("from the previous build\n")

    assert _run(cli, env, "ide", "update").returncode == 0
    assert not (app / "stale-file").exists()
    assert not app.with_suffix(".old").exists()
    assert (app / "antigravity-ide-bin").is_file()


def test_reinstall_clears_the_user_side_caches(world, tmp_path):
    """The deep variant. Settings, extensions and the login survive - a
    reinstall is for a crash loop, not a reset."""
    cli, tarball, sha, bin_dir, env = world
    _mock(bin_dir, "curl", _curl_mock(tarball, _api_payload(sha)))
    user = tmp_path / "home" / "dev" / ".config" / "Antigravity IDE"
    (user / "GPUCache").mkdir(parents=True)
    (user / "CachedData").mkdir()
    (user / "User").mkdir()
    (user / "User" / "settings.json").write_text("{}\n")

    r = _run(cli, env, "ide", "reinstall")
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    assert not (user / "GPUCache").exists()
    assert not (user / "CachedData").exists()
    assert (user / "User" / "settings.json").is_file()


def test_update_clears_the_gpu_cache_but_not_the_rest(world, tmp_path):
    """A version swap invalidates the compiled shader cache, which is a
    known renderer-crash source; the state caches are not the update's
    business."""
    cli, tarball, sha, bin_dir, env = world
    _mock(bin_dir, "curl", _curl_mock(tarball, _api_payload(sha)))
    user = tmp_path / "home" / "dev" / ".config" / "Antigravity IDE"
    (user / "GPUCache").mkdir(parents=True)
    (user / "CachedData").mkdir()

    assert _run(cli, env, "ide", "update").returncode == 0
    assert not (user / "GPUCache").exists()
    assert (user / "CachedData").exists()


# -- the router ---------------------------------------------------------


def test_an_unknown_command_prints_usage(world):
    cli, _tarball, _sha, _bin_dir, env = world
    r = _run(cli, env, "unknown-cmd")
    assert r.returncode == 1
    assert "Usage: gravity-cli <command> [options]" in r.stdout


def test_an_unknown_ide_subcommand_prints_usage(world):
    cli, _tarball, _sha, _bin_dir, env = world
    r = _run(cli, env, "ide", "downgrade")
    assert r.returncode == 1
    assert "Usage: gravity-cli <command> [options]" in r.stdout
