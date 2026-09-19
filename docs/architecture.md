# Build Architecture

## Layer Chain

Every Sanity-Gravity image is assembled through a **4-layer FROM chain**. Each layer is a standalone Dockerfile that accepts a `BASE_IMAGE` build argument, enabling composable stacking.

```
ubuntu:24.04 (pinned SHA)
 └─ Dockerfile.base                      → sanity-gravity:_base
     ├─ plugins/desktops/xfce/           → sanity-gravity:_base-xfce
     │   ├─ plugins/agents/ag/           → sanity-gravity:_ag-xfce → ag-xfce-{kasm,vnc,ssh}
     │   ├─ plugins/agents/agy/          → sanity-gravity:_agy-xfce → agy-xfce-{kasm,vnc,ssh}
     │   ├─ plugins/agents/cc/           → sanity-gravity:_cc-xfce → cc-xfce-{kasm,vnc,ssh}
     │   ├─ plugins/agents/cx/           → sanity-gravity:_cx-xfce → cx-xfce-{kasm,vnc,ssh}
     │   ├─ plugins/agents/gc/           → sanity-gravity:_gc-xfce → gc-xfce-{kasm,vnc,ssh}
     │   ├─ plugins/agents/oc/           → sanity-gravity:_oc-xfce → oc-xfce-{kasm,vnc,ssh}
     │   ├─ plugins/agents/ocd/          → sanity-gravity:_ocd-xfce → ocd-xfce-{kasm,vnc,ssh}
     │   └─ plugins/agents/dsh/          → sanity-gravity:_dsh-xfce → dsh-xfce-{kasm,vnc,ssh}
     ├─ plugins/desktops/lxqt/           → sanity-gravity:_base-lxqt
     │   ├─ plugins/agents/ag/           → sanity-gravity:_ag-lxqt → ag-lxqt-{kasm,vnc,ssh}
     │   ├─ plugins/agents/agy/          → sanity-gravity:_agy-lxqt → agy-lxqt-{kasm,vnc,ssh}
     │   ├─ plugins/agents/cc/           → sanity-gravity:_cc-lxqt → cc-lxqt-{kasm,vnc,ssh}
     │   ├─ plugins/agents/cx/           → sanity-gravity:_cx-lxqt → cx-lxqt-{kasm,vnc,ssh}
     │   ├─ plugins/agents/gc/           → sanity-gravity:_gc-lxqt → gc-lxqt-{kasm,vnc,ssh}
     │   ├─ plugins/agents/oc/           → sanity-gravity:_oc-lxqt → oc-lxqt-{kasm,vnc,ssh}
     │   ├─ plugins/agents/ocd/          → sanity-gravity:_ocd-lxqt → ocd-lxqt-{kasm,vnc,ssh}
     │   └─ plugins/agents/dsh/          → sanity-gravity:_dsh-lxqt → dsh-lxqt-{kasm,vnc,ssh}
     ├─ plugins/desktops/openbox/        → sanity-gravity:_base-openbox
     │   ├─ plugins/agents/ag/           → sanity-gravity:_ag-openbox → ag-openbox-{kasm,vnc,ssh}
     │   ├─ plugins/agents/agy/          → sanity-gravity:_agy-openbox → agy-openbox-{kasm,vnc,ssh}
     │   ├─ plugins/agents/cc/           → sanity-gravity:_cc-openbox → cc-openbox-{kasm,vnc,ssh}
     │   ├─ plugins/agents/cx/           → sanity-gravity:_cx-openbox → cx-openbox-{kasm,vnc,ssh}
     │   ├─ plugins/agents/gc/           → sanity-gravity:_gc-openbox → gc-openbox-{kasm,vnc,ssh}
     │   ├─ plugins/agents/oc/           → sanity-gravity:_oc-openbox → oc-openbox-{kasm,vnc,ssh}
     │   ├─ plugins/agents/ocd/          → sanity-gravity:_ocd-openbox → ocd-openbox-{kasm,vnc,ssh}
     │   └─ plugins/agents/dsh/          → sanity-gravity:_dsh-openbox → dsh-openbox-{kasm,vnc,ssh}
     └─ plugins/desktops/none/           → sanity-gravity:_base-none
         ├─ plugins/agents/agy/          → sanity-gravity:_agy-none → agy-none-ssh
         ├─ plugins/agents/cc/           → sanity-gravity:_cc-none → cc-none-ssh
         ├─ plugins/agents/cx/           → sanity-gravity:_cx-none → cx-none-ssh
         ├─ plugins/agents/gc/           → sanity-gravity:_gc-none → gc-none-ssh
         ├─ plugins/agents/oc/           → sanity-gravity:_oc-none → oc-none-ssh
         └─ plugins/agents/dsh/          → sanity-gravity:_dsh-none → dsh-none-ssh
```

(`ag` and `ocd` require a GUI desktop, so they have no headless `none` variant.)

Each non-base layer lives under `plugins/<kind>/<slug>/` alongside a
`manifest.toml` declaring its capabilities, ports, compose overlay, and
(for connectors) announce template. The kernel reads manifests at startup
via `lib/plugins.PluginRegistry`; adding a new agent/desktop/connector is
**a directory + two files** — no Python edits required (see PR #6).

## Naming Convention

- **Intermediate images** are prefixed with `_` (e.g. `sanity-gravity:_base-xfce`). They are local-only and never pushed to a registry.
- **Final images** use the full tag (e.g. `sanity-gravity:ag-xfce-kasm`). These are what you run and what CI publishes.

## How FROM Chaining Works

Every layered Dockerfile follows the same pattern:

```dockerfile
# Default is unused; always overridden by --build-arg. Set to suppress Docker warning.
ARG BASE_IMAGE=ubuntu:24.04
FROM ${BASE_IMAGE}

# Layer-specific instructions...
```

The CLI chains them via `--build-arg`:

```bash
docker build --build-arg BASE_IMAGE=sanity-gravity:_ag-xfce \
  -f plugins/connectors/kasm/Dockerfile \
  -t sanity-gravity:ag-xfce-kasm plugins/connectors/kasm
```

The base layer keeps `sandbox/` as its build context (so it can `COPY
rootfs /`); plugin layers each use **their own directory** as the
context, keeping the build hash deterministic and limiting each layer's
visibility to its own files.

## Cache Behavior

- `./sanity-cli build` checks for existing local images before building each layer. If a layer already exists, it's reported as a cache hit and skipped.
- Use `--no-cache` to force a full rebuild from scratch.
- Building a specific tag (e.g. `./sanity-cli build cc-none-ssh`) builds only the layers in that tag's chain.

## Build Phases

`./sanity-cli build` (with no arguments) builds all 19 **official** images in two phases; non-official tags (the deprecated `gc-*`, the community `ocd-*`, `dsh-*`, `*-lxqt-*` and `*-openbox-*`) build only when named explicitly:

1. **Phase 1: Intermediates** - builds the 12 shared intermediate images (`_base`, `_base-xfce`, `_base-none`, `_ag-xfce`, `_agy-xfce`, `_agy-none`, `_cc-xfce`, `_cc-none`, `_cx-xfce`, `_cx-none`, `_oc-xfce`, `_oc-none`).
2. **Phase 2: Finals** - builds all 19 official final images on top of the intermediates.

## Entrypoint

The base image (`Dockerfile.base`) installs `supervisord` as the process manager and `entrypoint.sh` as PID 1. At container start, the entrypoint:

1. Creates a user matching `HOST_UID` / `HOST_GID` / `HOST_USER`
2. Sets the password from `HOST_PASSWORD`
3. Grants passwordless sudo
4. Dynamically patches all supervisor configs to use the created username
5. Starts D-Bus (if installed), cleans stale locks, regenerates SSH host keys
6. Launches `supervisord` and traps `SIGTERM` for graceful shutdown

## Desktop Menu Entries

Every **agent plugin** reaches the desktop menu of the GUI tags. The same image also serves the headless `none` variants, where the entry is inert:

- CLI agents (`agy`, `cc`, `cx`, `gc`, `oc`) ship their own `.desktop` file under `rootfs/usr/share/applications/` (copied by `COPY rootfs/ /`) with `Terminal=true`, so clicking the entry runs the TUI inside the desktop's default terminal.
- IDE agents (`ag`) keep the GUI launcher the package installs (`antigravity.desktop`), patched for `--no-sandbox` in their Dockerfile.

## Desktop Session Launcher Contract

Every plugin that provides `display` ships `/usr/local/bin/desktop-session` (`xfce` writes a one-line `exec startxfce4`; `lxqt` writes `exec env <XDG session identity> startlxqt`; `openbox` writes `exec env <XDG session identity> openbox-session`), and the VNC-family connectors exec that one path from the `~/.vnc/xstartup` they write at container start - falling back to `startxfce4` only for images predating the contract, and starting `vncconfig -nowin` there so the X11 CLIPBOARD selection is bridged to the VNC clipboard - so adding a desktop never touches a connector, headless `none` tags have no session at all, and `tests/unit/test_desktop_session_contract.py` fails the build when a display plugin forgets the launcher.

## Bundled Browser

Every plugin that provides `display` runs one shared recipe, `/usr/local/lib/sanity-gravity/install-browser.sh`, staged into the base image by its `COPY rootfs /`: Google Chrome on amd64, Chromium on arm64 (Chrome has no Linux build there), a wrapper adding `--no-sandbox` — the browser's own sandbox needs privileges this container does not grant — and the `google-chrome` / `x-www-browser` links that every "open this link" path ends at. A plugin builds with its own directory as the build context, so the base rootfs is the one place three desktop Dockerfiles can share a file; the alternative is the same recipe copied into each of them. The headless `none` layer runs nothing, which is what keeps the `*-none-*` tags browser-free, and `tests/unit/test_desktop_browser.py` goes red the moment the set of plugins running the installer stops being the set that provides `display`.

## Openbox Entry Point

`openbox`'s `/usr/local/bin/desktop-session` execs `openbox-session` with `XDG_CURRENT_DESKTOP`, `DESKTOP_SESSION`, `XDG_SESSION_DESKTOP` and `XDG_SESSION_TYPE` set, which is what the openbox autostart and menu tooling read.

Openbox is a window manager with no panel and no desktop icons, so the plugin ships its own way into the installed agent: `/usr/local/bin/agent-starter`, reachable from the root menu, from a `Terminal=true` desktop entry, and from the session autostart.

The openbox layer is built before the agent layer, so the choice is made at runtime. `/usr/local/bin/launch-gui-agent` scans `/usr/share/applications/*.desktop` and prints the `Exec` command of a GUI IDE, matched on the command rather than the file name so a vendor rename does not break detection. When it prints nothing, `agent-starter` lists the project directories under `$HOME/workspace`, asks for one (offering to create the first), and execs the terminal agent it finds — claude, codex, gemini, opencode or agy — inside it; with no agent installed it opens a shell and prints `PATH` as a diagnostic.

The shipped `/etc/xdg/openbox/autostart` paints a solid background (a bare WM is otherwise black), merges `/etc/X11/Xresources/*` with `xrdb`, and opens the GUI agent or the `agent-starter` terminal. `rc.xml` points the root menu at the plugin's own `menu.xml` — the Debian default points at a file the uninstalled `menu` package would generate — and opens every normal window fullscreen so the main window fills the browser view (`A-F11` toggles, `A-F4` closes). The shipped Xresources route xterm selections to CLIPBOARD, the selection the VNC servers sync - without that, copying from the terminal to the browser silently does nothing - and they are keyed on the `xterm` instance name rather than the `XTerm` class, because `x-terminal-emulator` reaches xterm through `uxterm` under this image's UTF-8 locale, which runs it as class `UXTerm`.

## Filesystem Layout

```
sandbox/
├── Dockerfile.base             # Layer 1: base (build context = sandbox/)
└── rootfs/                     # Overlay copied into base image
    ├── usr/local/bin/
    │   ├── entrypoint.sh       # PID 1 init script
    │   └── gravity-cli         # In-container IDE management tool
    ├── usr/local/lib/sanity-gravity/
    │   └── install-browser.sh  # Browser recipe the desktop layers run
    └── etc/supervisor/
        ├── supervisord.conf    # Master config
        └── conf.d/ssh.conf     # sshd program definition

plugins/                        # Manifest-driven extension point (PR #6)
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
