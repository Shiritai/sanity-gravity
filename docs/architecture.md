# Build Architecture

## Layer Chain

Every Sanity-Gravity image is assembled through a **4-layer FROM chain**. Each layer is a standalone Dockerfile that accepts a `BASE_IMAGE` build argument, enabling composable stacking.

```
ubuntu:24.04 (pinned SHA)
 └─ Dockerfile.base                     → sanity-gravity:_base
     ├─ layers/desktops/xfce/           → sanity-gravity:_base-xfce
     │   ├─ layers/agents/ag/           → sanity-gravity:_ag-xfce
     │   │   ├─ layers/connectors/kasm/ → sanity-gravity:ag-xfce-kasm
     │   │   ├─ layers/connectors/vnc/  → sanity-gravity:ag-xfce-vnc
     │   │   └─ layers/connectors/ssh/  → sanity-gravity:ag-xfce-ssh
     │   ├─ layers/agents/gc/           → sanity-gravity:_gc-xfce  → gc-xfce-{kasm,vnc,ssh}
     │   └─ layers/agents/cc/           → sanity-gravity:_cc-xfce  → cc-xfce-{kasm,vnc,ssh}
     └─ layers/desktops/none/           → sanity-gravity:_base-none
         ├─ layers/agents/gc/           → sanity-gravity:_gc-none   → gc-none-ssh
         └─ layers/agents/cc/           → sanity-gravity:_cc-none   → cc-none-ssh
```

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
  -f sandbox/layers/connectors/kasm/Dockerfile \
  -t sanity-gravity:ag-xfce-kasm sandbox
```

## Cache Behavior

- `./sanity-cli build` checks for existing local images before building each layer. If a layer already exists, it's reported as a cache hit and skipped.
- Use `--no-cache` to force a full rebuild from scratch.
- Building a specific tag (e.g. `./sanity-cli build cc-none-ssh`) builds only the layers in that tag's chain.

## Build Phases

`./sanity-cli build` (with no arguments) builds all 11 images in two phases:

1. **Phase 1: Intermediates** — builds the 8 shared intermediate images (`_base`, `_base-xfce`, `_base-none`, `_ag-xfce`, `_gc-xfce`, `_cc-xfce`, `_gc-none`, `_cc-none`).
2. **Phase 2: Finals** — builds all 11 final images on top of the intermediates.

## Entrypoint

The base image (`Dockerfile.base`) installs `supervisord` as the process manager and `entrypoint.sh` as PID 1. At container start, the entrypoint:

1. Creates a user matching `HOST_UID` / `HOST_GID` / `HOST_USER`
2. Sets the password from `HOST_PASSWORD`
3. Grants passwordless sudo
4. Dynamically patches all supervisor configs to use the created username
5. Starts D-Bus (if installed), cleans stale locks, regenerates SSH host keys
6. Launches `supervisord` and traps `SIGTERM` for graceful shutdown

## Filesystem Layout

```
sandbox/
├── Dockerfile.base             # Layer 1: base
├── layers/
│   ├── desktops/
│   │   ├── xfce/Dockerfile     # Layer 2: XFCE4 desktop
│   │   └── none/Dockerfile     # Layer 2: headless (no-op)
│   ├── agents/
│   │   ├── ag/Dockerfile       # Layer 3: Antigravity IDE + Chrome
│   │   ├── gc/Dockerfile       # Layer 3: Node.js + Gemini CLI
│   │   └── cc/Dockerfile       # Layer 3: Claude Code CLI
│   └── connectors/
│       ├── kasm/               # Layer 4: KasmVNC + supervisor config
│       ├── vnc/                # Layer 4: TigerVNC + noVNC + supervisor config
│       └── ssh/                # Layer 4: SSH-only (EXPOSE 22)
└── rootfs/                     # Overlay copied into base image
    ├── usr/local/bin/
    │   ├── entrypoint.sh       # PID 1 init script
    │   └── gravity-cli         # In-container IDE management tool
    └── etc/supervisor/
        ├── supervisord.conf    # Master config
        └── conf.d/ssh.conf     # sshd program definition
```
