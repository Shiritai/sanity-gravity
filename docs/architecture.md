# Build Architecture

## Layer Chain

Every Sanity-Gravity image is assembled through a **4-layer FROM chain**. Each layer is a standalone Dockerfile that accepts a `BASE_IMAGE` build argument, enabling composable stacking.

```
plugins/base-images/ubuntu/ (ubuntu:24.04@sha256:…)
 └─ sandbox/Dockerfile.base              → sanity-gravity:_ubuntu
     ├─ plugins/desktops/xfce/           → sanity-gravity:_ubuntu-xfce
     │   ├─ plugins/agents/ag/           → sanity-gravity:_ubuntu-xfce-ag → ag-xfce-{kasm,vnc,ssh}
     │   ├─ plugins/agents/agy/          → sanity-gravity:_ubuntu-xfce-agy → agy-xfce-{kasm,vnc,ssh}
     │   ├─ plugins/agents/cc/           → sanity-gravity:_ubuntu-xfce-cc → cc-xfce-{kasm,vnc,ssh}
     │   ├─ plugins/agents/cx/           → sanity-gravity:_ubuntu-xfce-cx → cx-xfce-{kasm,vnc,ssh}
     │   ├─ plugins/agents/gc/           → sanity-gravity:_ubuntu-xfce-gc → gc-xfce-{kasm,vnc,ssh}
     │   ├─ plugins/agents/oc/           → sanity-gravity:_ubuntu-xfce-oc → oc-xfce-{kasm,vnc,ssh}
     │   ├─ plugins/agents/ocd/          → sanity-gravity:_ubuntu-xfce-ocd → ocd-xfce-{kasm,vnc,ssh}
     │   └─ plugins/agents/dsh/          → sanity-gravity:_ubuntu-xfce-dsh → dsh-xfce-{kasm,vnc,ssh}
     ├─ plugins/desktops/lxqt/           → sanity-gravity:_ubuntu-lxqt
     │   ├─ plugins/agents/ag/           → sanity-gravity:_ubuntu-lxqt-ag → ag-lxqt-{kasm,vnc,ssh}
     │   ├─ plugins/agents/agy/          → sanity-gravity:_ubuntu-lxqt-agy → agy-lxqt-{kasm,vnc,ssh}
     │   ├─ plugins/agents/cc/           → sanity-gravity:_ubuntu-lxqt-cc → cc-lxqt-{kasm,vnc,ssh}
     │   ├─ plugins/agents/cx/           → sanity-gravity:_ubuntu-lxqt-cx → cx-lxqt-{kasm,vnc,ssh}
     │   ├─ plugins/agents/gc/           → sanity-gravity:_ubuntu-lxqt-gc → gc-lxqt-{kasm,vnc,ssh}
     │   ├─ plugins/agents/oc/           → sanity-gravity:_ubuntu-lxqt-oc → oc-lxqt-{kasm,vnc,ssh}
     │   ├─ plugins/agents/ocd/          → sanity-gravity:_ubuntu-lxqt-ocd → ocd-lxqt-{kasm,vnc,ssh}
     │   └─ plugins/agents/dsh/          → sanity-gravity:_ubuntu-lxqt-dsh → dsh-lxqt-{kasm,vnc,ssh}
     ├─ plugins/desktops/openbox/        → sanity-gravity:_ubuntu-openbox
     │   ├─ plugins/agents/ag/           → sanity-gravity:_ubuntu-openbox-ag → ag-openbox-{kasm,vnc,ssh}
     │   ├─ plugins/agents/agy/          → sanity-gravity:_ubuntu-openbox-agy → agy-openbox-{kasm,vnc,ssh}
     │   ├─ plugins/agents/cc/           → sanity-gravity:_ubuntu-openbox-cc → cc-openbox-{kasm,vnc,ssh}
     │   ├─ plugins/agents/cx/           → sanity-gravity:_ubuntu-openbox-cx → cx-openbox-{kasm,vnc,ssh}
     │   ├─ plugins/agents/gc/           → sanity-gravity:_ubuntu-openbox-gc → gc-openbox-{kasm,vnc,ssh}
     │   ├─ plugins/agents/oc/           → sanity-gravity:_ubuntu-openbox-oc → oc-openbox-{kasm,vnc,ssh}
     │   ├─ plugins/agents/ocd/          → sanity-gravity:_ubuntu-openbox-ocd → ocd-openbox-{kasm,vnc,ssh}
     │   └─ plugins/agents/dsh/          → sanity-gravity:_ubuntu-openbox-dsh → dsh-openbox-{kasm,vnc,ssh}
     └─ plugins/desktops/none/           → sanity-gravity:_ubuntu-none
         ├─ plugins/agents/agy/          → sanity-gravity:_ubuntu-none-agy → agy-none-ssh
         ├─ plugins/agents/cc/           → sanity-gravity:_ubuntu-none-cc → cc-none-ssh
         ├─ plugins/agents/cx/           → sanity-gravity:_ubuntu-none-cx → cx-none-ssh
         ├─ plugins/agents/gc/           → sanity-gravity:_ubuntu-none-gc → gc-none-ssh
         ├─ plugins/agents/oc/           → sanity-gravity:_ubuntu-none-oc → oc-none-ssh
         └─ plugins/agents/dsh/          → sanity-gravity:_ubuntu-none-dsh → dsh-none-ssh
```

(`ag` and `ocd` require a GUI desktop, so they have no headless `none` variant.)

The tree above is the default `ubuntu` base. Every other base grows the same tree from its own root layer, built from the same `sandbox/Dockerfile.base` on that base's pinned upstream image, and its final images carry the base as a trailing tag segment. One chain on `debian`:

```
plugins/base-images/debian/ (debian:12-slim@sha256:…)
 └─ sandbox/Dockerfile.base → _debian → _debian-xfce → _debian-xfce-cc → cc-xfce-kasm-debian
```

Every layer, the base included, lives under `plugins/<kind>/<slug>/` (kinds: `base-images`, `desktops`, `agents`, `connectors`) alongside a `manifest.toml` declaring its capabilities, ports, compose overlay, and (for connectors) announce template. The kernel reads manifests at startup via `PluginRegistry` (`sanity_gravity/plugins/registry.py`); adding a new base/agent/desktop/connector is **a directory + a manifest** (plus a Dockerfile for every kind but a base, which points at the shared one) — no Python edits required (see PR #6).

## Naming Convention

- **Intermediate images** are prefixed with `_` and named by their build path: the slugs bound so far, in build order (base, desktop, agent), so the segment count is the number of bound dimensions and a layer's name is its parent's name plus one segment (e.g. `sanity-gravity:_ubuntu-xfce` -> `sanity-gravity:_ubuntu-xfce-ag`). The base is always spelled out here, even the default one. They are local-only and never pushed to a registry.
- **Final images** use the full tag (e.g. `sanity-gravity:ag-xfce-kasm`, `sanity-gravity:ag-xfce-kasm-debian`). These are what you run and what CI publishes (official tags only).

## How FROM Chaining Works

Every plugin layer's Dockerfile follows the same pattern:

```dockerfile
# Default is unused; always overridden by --build-arg. Set to suppress Docker warning.
ARG BASE_IMAGE=ubuntu:24.04
FROM ${BASE_IMAGE}

# Layer-specific instructions...
```

The CLI chains them via `--build-arg`:

```bash
docker build --build-arg BASE_IMAGE=sanity-gravity:_ubuntu-xfce-ag \
  -f plugins/connectors/kasm/Dockerfile \
  -t sanity-gravity:ag-xfce-kasm plugins/connectors/kasm
```

The root layer's `BASE_IMAGE` is the digest-pinned upstream image in its base plugin's `[build].from` (e.g. `ubuntu:24.04@sha256:…`); every other layer gets its parent layer's image. `sandbox/Dockerfile.base` has no default for it, so a build without `--build-arg` fails instead of picking a distro.

A base plugin's manifest points its build context at the shared `sandbox/` tree (so the Dockerfile can `COPY rootfs /`); the other plugin layers each use **their own directory** as the context, keeping the build hash deterministic and limiting each layer's visibility to its own files.

## Cache Behavior

- `./sanity-cli build` checks for existing local images before building each layer. If a layer already exists, it's reported as a cache hit and skipped.
- Use `--no-cache` to force a full rebuild from scratch.
- Building a specific tag (e.g. `./sanity-cli build cc-none-ssh`) builds only the layers in that tag's chain.

## Build Phases

`./sanity-cli build` (with no arguments) builds all 19 **official** images in two phases; non-official tags (the deprecated `gc-*`, the community `ocd-*`, `dsh-*`, `*-lxqt-*`, `*-openbox-*` and `*-debian`) build only when named explicitly:

1. **Phase 1: Intermediates** - builds the 12 shared intermediate images (`_ubuntu`, `_ubuntu-xfce`, `_ubuntu-none`, `_ubuntu-xfce-ag`, `_ubuntu-xfce-agy`, `_ubuntu-none-agy`, `_ubuntu-xfce-cc`, `_ubuntu-none-cc`, `_ubuntu-xfce-cx`, `_ubuntu-none-cx`, `_ubuntu-xfce-oc`, `_ubuntu-none-oc`).
2. **Phase 2: Finals** - builds all 19 official final images on top of the intermediates.

## Entrypoint

The base image (`sandbox/Dockerfile.base`) installs `supervisord` as the process manager and `entrypoint.sh` as PID 1. At container start, the entrypoint:

1. Creates a user matching `HOST_UID` / `HOST_GID` / `HOST_USER`
2. Sets the password from `HOST_PASSWORD`
3. Grants passwordless sudo
4. Dynamically patches all supervisor configs to use the created username
5. Starts D-Bus (if installed), cleans stale locks, regenerates SSH host keys
6. Launches `supervisord` and traps `SIGTERM` for graceful shutdown

## Desktop Menu Entries

Every **agent plugin** reaches the desktop menu of the GUI tags. The same image also serves the headless `none` variants, where the entry is inert:

- CLI agents (`agy`, `cc`, `cx`, `gc`, `oc`) ship their own `.desktop` file under `rootfs/usr/share/applications/` (copied by `COPY rootfs/ /`) with `Terminal=true`, so clicking the entry runs the TUI inside the desktop's default terminal.
- IDE agents (`ag`) write their own: the Antigravity IDE 2.x tarball ships no `.desktop` file at all, so `gravity-cli` installs a menu entry (`Exec=/usr/bin/antigravity-ide`, `StartupWMClass=antigravity-ide`) and a `NoDisplay=true` handler entry claiming `x-scheme-handler/antigravity-ide` - the scheme Google sign-in returns over. The sandbox flags sit in the wrapper the entry reaches, not in `Exec`.

## Desktop Session Launcher Contract

Every plugin that provides `display` ships `/usr/local/bin/desktop-session` (`xfce` writes a one-line `exec startxfce4`; `lxqt` writes `exec env <XDG session identity> startlxqt`; `openbox` writes `exec env <XDG session identity> openbox-session`), and the VNC-family connectors exec that one path from the `~/.vnc/xstartup` they write at container start - falling back to `startxfce4` only for images predating the contract, and starting `vncconfig -nowin` there so the X11 CLIPBOARD selection is bridged to the VNC clipboard - so adding a desktop never touches a connector, headless `none` tags have no session at all, and `tests/unit/test_desktop_session_contract.py` fails the build when a display plugin forgets the launcher.

## Bundled Browser

Every plugin that provides `display` runs one shared recipe, `/usr/local/lib/sanity-gravity/install-browser.sh`, staged into the base image by its `COPY rootfs /`: Google Chrome on amd64, Chromium on arm64 (Chrome has no Linux build there), a wrapper adding `--no-sandbox` — the browser's own sandbox needs privileges this container does not grant — and the `google-chrome` / `x-www-browser` links that every "open this link" path ends at. A plugin builds with its own directory as the build context, so the base rootfs is the one place three desktop Dockerfiles can share a file; the alternative is the same recipe copied into each of them. The headless `none` layer runs nothing, which is what keeps the `*-none-*` tags browser-free, and `tests/unit/test_desktop_browser.py` goes red the moment the set of plugins running the installer stops being the set that provides `display`.

## Openbox Entry Point

`openbox`'s `/usr/local/bin/desktop-session` execs `openbox-session` with `XDG_CURRENT_DESKTOP`, `DESKTOP_SESSION`, `XDG_SESSION_DESKTOP` and `XDG_SESSION_TYPE` set, which is what the openbox autostart and menu tooling read.

Openbox is a window manager with no panel and no desktop icons, so the plugin ships its own way into the installed agent: `/usr/local/bin/agent-starter`, reachable from the root menu, from a `Terminal=true` desktop entry, and from the session autostart.

The openbox layer is built before the agent layer, so the choice is made at runtime. `/usr/local/bin/launch-gui-agent` scans `/usr/share/applications/*.desktop` and prints the `Exec` command of a GUI IDE, matched on the base name of the program (`antigravity-ide`, `ai.opencode.desktop`) rather than the file name, so a vendor moving its install prefix does not break detection while a vendor renaming the program does; `tests/unit/test_launch_gui_agent.py` runs it against fixture entry directories. When it prints nothing, `agent-starter` lists the project directories under `$HOME/workspace`, asks for one (offering to create the first), and execs the terminal agent it finds — claude, codex, gemini, opencode or agy — inside it; with no agent installed it opens a shell and prints `PATH` as a diagnostic.

The shipped `/etc/xdg/openbox/autostart` paints a solid background (a bare WM is otherwise black), merges `/etc/X11/Xresources/*` with `xrdb`, and opens the GUI agent or the `agent-starter` terminal. `rc.xml` points the root menu at the plugin's own `menu.xml` — the Debian default points at a file the uninstalled `menu` package would generate — and opens every normal window fullscreen so the main window fills the browser view (`A-F11` toggles, `A-F4` closes). The shipped Xresources route xterm selections to CLIPBOARD, the selection the VNC servers sync - without that, copying from the terminal to the browser silently does nothing - and they are keyed on the `xterm` instance name rather than the `XTerm` class, because `x-terminal-emulator` reaches xterm through `uxterm` under this image's UTF-8 locale, which runs it as class `UXTerm`.

## Filesystem Layout

```
sandbox/
├── Dockerfile.base             # Layer 1: shared by every base (build context = sandbox/)
└── rootfs/                     # Overlay copied into base image
    ├── usr/local/bin/
    │   └── entrypoint.sh       # PID 1 init script
    ├── usr/local/lib/sanity-gravity/
    │   └── install-browser.sh  # Browser recipe the desktop layers run
    └── etc/supervisor/
        ├── supervisord.conf    # Master config
        └── conf.d/ssh.conf     # sshd program definition

plugins/                        # Manifest-driven extension point (PR #6)
├── base-images/
│   ├── ubuntu/                 # Layer 1: Ubuntu 24.04 (default)
│   │   └── manifest.toml       #   [build].from = pinned ubuntu:24.04, provides=[ubuntu:noble]
│   └── debian/                 # Layer 1: Debian 12 (bookworm)
│       └── manifest.toml       #   [build].from = pinned debian:12-slim, provides=[debian:bookworm], tier=community
├── desktops/
│   ├── xfce/                   # Layer 2: XFCE4 desktop
│   │   ├── manifest.toml       #   provides=[display]
│   │   └── Dockerfile
│   ├── lxqt/                   # Layer 2: LXQt desktop
│   │   ├── manifest.toml       #   provides=[display], tier=community
│   │   └── Dockerfile
│   ├── openbox/                # Layer 2: Openbox window manager
│   │   ├── manifest.toml       #   provides=[display], tier=community
│   │   ├── Dockerfile
│   │   └── rootfs/             #   agent-starter, openbox config, Xresources
│   └── none/                   # Layer 2: headless (no-op)
│       ├── manifest.toml
│       └── Dockerfile
├── agents/
│   ├── ag/                     # Layer 3: Antigravity IDE
│   │   ├── manifest.toml       #   requires=[display]
│   │   └── Dockerfile
│   ├── agy/                    # Layer 3: Antigravity CLI
│   │   ├── manifest.toml
│   │   └── Dockerfile
│   ├── cc/                     # Layer 3: Claude Code CLI
│   │   ├── manifest.toml
│   │   └── Dockerfile
│   ├── cx/                     # Layer 3: OpenAI Codex CLI (codex binary)
│   │   ├── manifest.toml
│   │   └── Dockerfile
│   ├── gc/                     # Layer 3: Node.js + Gemini CLI
│   │   ├── manifest.toml
│   │   └── Dockerfile
│   ├── oc/                     # Layer 3: OpenCode CLI (opencode binary)
│   │   ├── manifest.toml
│   │   └── Dockerfile
│   └── ocd/                    # Layer 3: OpenCode Desktop (Electron GUI)
│       ├── manifest.toml       #   requires=[display]
│       └── Dockerfile
└── connectors/
    ├── kasm/                   # Layer 4: KasmVNC + supervisor config
    │   ├── manifest.toml       #   ports/compose/announce
    │   ├── Dockerfile
    │   ├── supervisord.conf
    │   └── startup.sh
    ├── vnc/                    # Layer 4: TigerVNC + noVNC + supervisor config
    │   ├── manifest.toml
    │   ├── Dockerfile
    │   ├── supervisord.conf
    │   └── startup.sh
    └── ssh/                    # Layer 4: SSH-only (EXPOSE 22)
        ├── manifest.toml
        └── Dockerfile
```

### Adding a new plugin

```bash
mkdir -p plugins/connectors/rdp
$EDITOR plugins/connectors/rdp/{manifest.toml,Dockerfile}
./sanity-cli plugins list   # verify it registered
./sanity-cli list           # see new tag combinations appear
```

No core code edits — the kernel re-discovers the plugin tree on each run.

## CLI Package Layout

The `sanity-cli` script at the repo root is a thin shim. All CLI logic lives
in the `sanity_gravity/` package next to it:

```
sanity_gravity/
├── cli/         # argparse setup + entry point + dispatch
├── verbs/       # one file per CLI verb (build, up, down, status, …)
├── core/        # microkernel: orchestrator, eventbus, reporter, command
├── domain/      # pure data: Tag, Phase, capability solver
├── effects/     # Effect-First execution: Action types + Executor (dry-run)
├── compose/     # type-safe docker-compose YAML builder
├── plugins/     # manifest loader + PluginRegistry
├── infra/       # I/O implementations (proxy_manager, …)
└── events.py    # event hierarchy emitted by Reporter
```

Layer rules (enforced by code review, not yet by import-linter):

- `domain/` imports nothing else in the package (pure).
- `core/` may import from `domain/`.
- `compose/`, `plugins/`, `effects/` may import from `core/` and `domain/`.
- `verbs/` may import from anywhere except `cli/`.
- `cli/` is the entry layer; it imports `verbs/` and dispatches.

Tests live under `tests/unit/` (no Docker required) and `tests/integration/`
(spin up real containers).
