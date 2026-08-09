# Build Architecture

## Layer Chain

Every Sanity-Gravity image is assembled through a **4-layer FROM chain**. Each layer is a standalone Dockerfile that accepts a `BASE_IMAGE` build argument, enabling composable stacking.

```
ubuntu:24.04 (pinned SHA) / debian:12 (pinned SHA)   ← base dimension (ubuntu default)
 └─ base plugin Dockerfile                            → sanity-gravity:_base         (ubuntu)
                                                      → sanity-gravity:_debian_base  (debian)
     ├─ plugins/desktops/xfce/                        → _base-xfce / _debian_base-xfce
     │   ├─ plugins/agents/ag/                        → _ag-xfce / _debian_ag-xfce → ag-xfce-{kasm,vnc,ssh} / debian-ag-xfce-{kasm,vnc,ssh}
     │   ├─ plugins/agents/agy/                       → _agy-xfce / _debian_agy-xfce
     │   ├─ plugins/agents/cc/                        → _cc-xfce / _debian_cc-xfce
     │   ├─ plugins/agents/cx/                        → _cx-xfce / _debian_cx-xfce
     │   ├─ plugins/agents/gc/                        → _gc-xfce / _debian_gc-xfce
     │   └─ plugins/agents/oc/                        → _oc-xfce / _debian_oc-xfce
     ├─ plugins/desktops/cinnamon/                    → _base-cinnamon / _debian_base-cinnamon
     │   └─ plugins/agents/*/                         → _*-cinnamon / _debian_*-cinnamon
     ├─ plugins/desktops/lxqt/                        → _base-lxqt / _debian_base-lxqt
     │   └─ plugins/agents/*/                         → _*-lxqt / _debian_*-lxqt
     ├─ plugins/desktops/openbox/                     → _base-openbox / _debian_base-openbox
     │   └─ plugins/agents/*/                         → _*-openbox / _debian_*-openbox
     └─ plugins/desktops/none/                        → _base-none / _debian_base-none
         ├─ plugins/agents/agy/                       → _agy-none / _debian_agy-none → agy-none-ssh / debian-agy-none-ssh
         ├─ plugins/agents/cc/                        → _cc-none / _debian_cc-none
         ├─ plugins/agents/cx/                        → _cx-none / _debian_cx-none
         ├─ plugins/agents/gc/                        → _gc-none / _debian_gc-none
         └─ plugins/agents/oc/                        → _oc-none / _debian_oc-none
```

(`ag` requires a GUI desktop, so it has no headless `none` variant.)

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

`./sanity-cli build` (with no arguments) builds all 19 **official** images in two phases; non-official tags (e.g. the deprecated `gc-*`) build only when named explicitly:

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

## Desktop Session Launcher Contract

The VNC-family connectors (`kasm`, `vnc`) start a graphical session at
container start. Desktop plugins own that launcher contract: each GUI
desktop ships a `/usr/local/bin/desktop-session` entry point, so the
connectors can invoke one stable command and the browser/VNC window always
shows the desktop environment. `xfce` ships the contract as a one-liner
(`exec startxfce4`); `openbox` via `openbox-session`. Headless `none`
tags have no desktop and no session file.

The **openbox** desktop ships its own entry point: `agent-starter` at
`/usr/local/bin/agent-starter` (plus a `Terminal=true` `.desktop` entry and
a right-click root-menu item). Openbox is just a window manager with no
panel or desktop icons, so this script is how a user reaches the installed
agent. It decides at runtime (the openbox layer is built before the agent
layers):

- **GUI agents** (`ag` Antigravity IDE, `od` OpenCode Desktop): detected via
  their `.desktop` launchers by `/usr/local/bin/launch-gui-agent`, which
  scans all `/usr/share/applications/*.desktop` entries and matches by the
  `Exec=` marker of the GUI binaries (`/opt/OpenCode/ai.opencode.desktop`,
  `/usr/bin/antigravity`), so it works regardless of the shipped desktop-file
  name. The session autostart launches the GUI IDE as the main window
  instead of a terminal, so it is immediately usable in the KasmVNC / noVNC
  browser view. `agent-starter` does the same when opened from the menu.
- **CLI agents** (`agy`, `cc`, `cx`, `gc`, `oc`): the script lists the
  subprojects under `$HOME/workspace`, lets the user pick one, and execs the
  agent present at runtime (claude / codex / gemini / opencode / agy). The
  detection combines `command -v` with absolute-path fallbacks for the known
  install locations, so it also works if the session's `PATH` omits
  `/usr/local/bin` (where `opencode` and the Antigravity CLI `agy` land). If
  no project exists yet it prompts for a name, creates the directory and
  starts the agent inside it. With no agent at all it falls back to a plain
  shell and prints the current `PATH` as a diagnostic.

The shipped `/etc/xdg/openbox/autostart` paints a solid background (a bare
WM is otherwise pitch-black), launches the GUI agent or the `agent-starter`
terminal at session start, and runs XDG autostart entries (its
`openbox-xdg-autostart` needs `python3-xdg`, installed by the plugin). A
custom `rc.xml` wires the right-click root menu to the plugin's `menu.xml`
instead of the missing Debian `debian-menu.xml`, and its `<applications>`
rules open every normal window (the Agent Starter terminal as well as GUI
IDEs) fullscreen, so the main app fills the VNC browser view immediately
(`A-F11` toggles fullscreen, `A-F4` closes the window). Readability over
VNC is handled by `fonts-dejavu-core`: the theme uses DejaVu Sans at 10pt
for the titlebar/menus/OSDs, and the shipped `/etc/X11/Xresources/xterm` (a
file in the Debian-standard directory) is merged via `xrdb` by the
connector xstartup (and again by the openbox autostart) so xterm
(agent-starter terminal and CLI-agent TUIs) renders in DejaVu Sans Mono at
10pt instead of its tiny 8pt default. The same resource file sets
`XTerm*selectToClipboard: true`, which routes xterm selections to the
CLIPBOARD selection instead of PRIMARY — without it, the VNC servers do not
see selected terminal text and copy/paste to the browser fails.

## Filesystem Layout

```
sandbox/
├── Dockerfile.base             # Layer 1: base (build context = sandbox/)
└── rootfs/                     # Overlay copied into base image
    ├── usr/local/bin/
    │   ├── entrypoint.sh       # PID 1 init script
    │   └── gravity-cli         # In-container IDE management tool
    └── etc/supervisor/
        ├── supervisord.conf    # Master config
        └── conf.d/ssh.conf     # sshd program definition

plugins/                        # Manifest-driven extension point (PR #6)
├── desktops/
│   ├── xfce/                   # Layer 2: XFCE4 desktop
│   │   ├── manifest.toml       #   provides=[display]
│   │   └── Dockerfile
│   ├── lxqt/                   # Layer 2: LXQt desktop
│   │   ├── manifest.toml       #   provides=[display]
│   │   └── Dockerfile
│   ├── openbox/                # Layer 2: Openbox window manager
│   │   ├── manifest.toml       #   provides=[display]
│   │   ├── Dockerfile
│   │   └── rootfs/             #   agent-starter entry + openbox menu
│   └── none/                   # Layer 2: headless (no-op)
│       ├── manifest.toml
│       └── Dockerfile
├── agents/
│   ├── ag/                     # Layer 3: Antigravity IDE + Chrome
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
│   └── oc/                     # Layer 3: OpenCode CLI (opencode binary)
│       ├── manifest.toml
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
