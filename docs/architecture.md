# Build Architecture

## Layer Chain

Every Sanity-Gravity image is assembled through a **4-layer FROM chain**. Each layer is a standalone Dockerfile that accepts a `BASE_IMAGE` build argument, enabling composable stacking.

The first layer is the **base OS image**, selected by the tag's base dimension. `ubuntu` is the default (its intermediate keeps the legacy unprefixed names); other bases are prefixed:

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
     └─ plugins/desktops/none/                        → _base-none / _debian_base-none
         ├─ plugins/agents/agy/                       → _agy-none / _debian_agy-none → agy-none-ssh / debian-agy-none-ssh
         ├─ plugins/agents/cc/                        → _cc-none / _debian_cc-none
         ├─ plugins/agents/cx/                        → _cx-none / _debian_cx-none
         ├─ plugins/agents/gc/                        → _gc-none / _debian_gc-none
         └─ plugins/agents/oc/                        → _oc-none / _debian_oc-none
```

(`ag` requires a GUI desktop, so it has no headless `none` variant.)

The base image is itself a manifest-driven plugin: `plugins/base-images/ubuntu/`
owns the canonical base `Dockerfile` (the default OS layer; it builds with
`sandbox/` as its context so `COPY rootfs /` resolves — see
`hooks/build._build_context_for`); `plugins/base-images/debian/` ships its own
`Dockerfile` built on pinned `debian:12`. Each non-base layer lives under
`plugins/<kind>/<slug>/` alongside a `manifest.toml` declaring its
capabilities, ports, compose overlay, and (for connectors) announce
template. The kernel reads manifests at startup via
`lib/plugins.PluginRegistry`; adding a new agent/desktop/connector/base is
**a directory + two files** — no Python edits required (see PR #6).

## Naming Convention

- **Intermediate images** are prefixed with `_`. The default base keeps
  its legacy names (`_base`, `_base-{desktop}`, `_{agent}-{desktop}`);
  other bases are prefixed with their slug
  (`_debian_base`, `_debian_base-{desktop}`, `_debian_{agent}-{desktop}`).
  Intermediates are local-only and never pushed to a registry.
- **Final images** use the full tag. Tags on the default base omit the
  base prefix (e.g. `sanity-gravity:ag-xfce-kasm`); non-default bases are
  prefixed (e.g. `sanity-gravity:debian-ag-xfce-kasm`). These are what you
  run and what CI publishes.

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

`./sanity-cli build` (with no arguments) builds all **38 official** images
in two phases; non-official tags (e.g. the deprecated `gc-*`) build only
when named explicitly:

1. **Phase 1: Intermediates** - builds the shared intermediate images
   (`_base`, `_debian_base`, `_base-*`, `_debian_base-*`, `_{agent}-{desktop}`,
   `_debian_{agent}-{desktop}` — one per base).
2. **Phase 2: Finals** - builds all 38 official final images (19 per base)
   on top of the intermediates.

`--layer base|desktop|agent|connector` builds up to a layer type (CI use);
`--layer-target` narrows it to a specific slug (e.g. `debian`,
`xfce`, `debian-ag-xfce`).

## Entrypoint

The base image (`plugins/base-images/ubuntu/Dockerfile`) installs `supervisord` as the process manager and `entrypoint.sh` as PID 1. At container start, the entrypoint:

1. Creates a user matching `HOST_UID` / `HOST_GID` / `HOST_USER`
2. Sets the password from `HOST_PASSWORD`
3. Grants passwordless sudo
4. Dynamically patches all supervisor configs to use the created username
5. Starts D-Bus (if installed), cleans stale locks, regenerates SSH host keys
6. Launches `supervisord` and traps `SIGTERM` for graceful shutdown

## Filesystem Layout

```
sandbox/
└── rootfs/                     # Overlay copied into base image
    ├── usr/local/bin/
    │   ├── entrypoint.sh       # PID 1 init script
    │   └── gravity-cli         # In-container IDE management tool
    └── etc/supervisor/
        ├── supervisord.conf    # Master config
        └── conf.d/ssh.conf     # sshd program definition

plugins/                        # Manifest-driven extension point (PR #6)
├── base-images/                # Layer 1: base OS images
│   ├── ubuntu/                 #   default — owns the canonical base Dockerfile
│   │   ├── manifest.toml
│   │   └── Dockerfile
│   └── debian/                 #   alternative — pinned debian:12
│       ├── manifest.toml
│       └── Dockerfile
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
