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
     │   └─ plugins/agents/oc/           → sanity-gravity:_oc-xfce → oc-xfce-{kasm,vnc,ssh}
     └─ plugins/desktops/none/           → sanity-gravity:_base-none
         ├─ plugins/agents/agy/          → sanity-gravity:_agy-none → agy-none-ssh
         ├─ plugins/agents/cc/           → sanity-gravity:_cc-none → cc-none-ssh
         ├─ plugins/agents/cx/           → sanity-gravity:_cx-none → cx-none-ssh
         ├─ plugins/agents/gc/           → sanity-gravity:_gc-none → gc-none-ssh
         └─ plugins/agents/oc/           → sanity-gravity:_oc-none → oc-none-ssh
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

Every **agent plugin** additionally ships a `.desktop` menu entry via
`rootfs/usr/share/applications/` (`COPY rootfs/ /`) so the tool appears in
the desktop menu. The same image serves the headless `none` variants, where
the file is simply inert:

- IDE agents (`ag`) keep the GUI launcher the package installs
  (`antigravity.desktop`), patched for `--no-sandbox` in their Dockerfile.
- CLI agents (`agy`, `cc`, `cx`, `gc`, `oc`) ship a `.desktop` file with
  `Terminal=true`, so clicking the entry runs the TUI inside the desktop's
  default terminal.

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
