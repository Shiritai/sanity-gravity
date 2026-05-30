# CLI Reference

`sanity-cli` is the central orchestrator for building, running, and managing Sanity-Gravity sandbox containers.

## Prerequisites

```bash
./sanity-cli check
```

Verifies that Docker and Docker Compose (v2.0+) are installed and the Docker daemon is running.

---

## Build Commands

### `build [tag...]`

Build sandbox images. Defaults to building all 11 valid tags.

```bash
./sanity-cli build              # Build all images
./sanity-cli build ag-xfce-kasm # Build a specific tag (and its intermediate layers)
./sanity-cli build cc-none-ssh gc-none-ssh  # Build multiple tags
```

| Flag | Description |
|:-----|:------------|
| `--no-cache` | Disable Docker layer cache |
| `--layer {base,desktop,agent,connector}` | Build only up to a specific layer (CI use) |
| `--layer-target <target>` | Target within `--layer` (e.g. `xfce`, `ag-xfce`) |
| `--list-intermediates` | Print intermediate image names and exit |
| `--json` | Output in JSON format (with `--list-intermediates`) |

### `list`

Print all valid tags and the dimension matrix.

```bash
./sanity-cli list               # Human-readable output
./sanity-cli list --json        # JSON array (for CI matrix)
```

---

## Lifecycle Commands

### `pull`

Explicitly fetch pre-built sandbox images from GitHub Container Registry (GHCR) and retag them for local use (Local Tag Normalization). 
By default, `up` will automatically invoke this if a local image is missing.

```bash
./sanity-cli pull                 # Pull all variants
./sanity-cli pull agy-xfce-ssh    # Pull a specific variant
./sanity-cli pull agy-none-ssh --tag v0.3.0-rc.3  # Pull a specific version
```

### `up`

Create and start a sandbox container.

```bash
./sanity-cli up -v ag-xfce-kasm
./sanity-cli up -v cc-none-ssh --name my-agent --workspace ~/projects
```

| Flag | Default | Description |
|:-----|:--------|:------------|
| `-v, --variant <tag>` | *(required)* | Tag to run (e.g. `ag-xfce-kasm`) |
| `--pull` | off | Force pull latest GHCR image before starting |
| `-p, --ssh-port <port>` | `2222` | Host port for SSH |
| `--kasm-port <port>` | `8444` | Host port for KasmVNC |
| `--vnc-port <port>` | `5901` | Host port for VNC |
| `--novnc-port <port>` | `6901` | Host port for noVNC |
| `--password <pwd>` | `antigravity` | Password for SSH/VNC/KasmVNC |
| `--skip-check` | off | Skip Docker prerequisite checks |
| `-w, --workspace <path>` | `./workspace` | Host directory to mount |
| `-n, --name <name>` | `sanity-gravity` | Docker Compose project name |
| `--cpus <limit>` | *(none)* | CPU quota (e.g. `1.5`) |
| `--memory <limit>` | *(none)* | Memory limit (e.g. `4G`) |
| `--image <image>` | *(none)* | Use a custom/snapshot image |

**Port auto-allocation**: When `--name` differs from the default `sanity-gravity`, ports are automatically set to ephemeral (random free port) unless explicitly provided.

### `down`

Stop and remove containers and networks.

```bash
./sanity-cli down
./sanity-cli down --name dev-02
```

### `stop`

Pause containers without removing them. Data is preserved.

### `start`

Resume stopped containers.

### `restart`

Force restart running containers.

### `clean`

Deep cleanup: remove containers, volumes, and local images.

```bash
./sanity-cli clean --name sanity-gravity
./sanity-cli clean --force      # Skip confirmation prompt
```

All lifecycle commands accept `-n, --name` to target a specific instance.

---

## Inspection Commands

### `status`

Show running sandbox instances and their port mappings.

### `shell`

Drop into a container's shell. Defaults to zsh, falling back to bash if zsh is unavailable.

```bash
./sanity-cli shell                      # zsh, auto-fallback to bash on failure
./sanity-cli shell --name dev-02
./sanity-cli shell --user root
./sanity-cli shell --use bash           # explicit bash, no fallback
./sanity-cli shell --use zsh            # explicit zsh, no fallback
```

| Flag | Description |
|:-----|:------------|
| `-n, --name` | Project name (default: `sanity-gravity`) |
| `-u, --user` | User to login as (default: container's `HOST_USER`, typically `developer`) |
| `--use {zsh,bash}` | Explicit shell choice. Disables the zsh → bash auto-fallback. |

### `open`

Open the web desktop (KasmVNC/noVNC) URL in the default browser.

---

## Maintenance Commands

### `ide <action>`

Remotely manage the Antigravity IDE inside a running container.

```bash
./sanity-cli ide update --name sanity-gravity     # Safe upgrade via apt
./sanity-cli ide reinstall --name sanity-gravity   # Full purge + reinstall
```

These commands auto-inject the latest `gravity-cli` protection script into the target container before execution.

### `proxy <action>`

Manage the SSH Agent Socket Proxy that bridges host SSH keys into containers.

```bash
./sanity-cli proxy setup    # Start the proxy daemon
./sanity-cli proxy status   # Check proxy and connection health
./sanity-cli proxy remove   # Stop and remove the proxy
```

### `sync_config`

Push host-side configuration files to a running container's `~/.gemini/` directory.

```bash
./sanity-cli sync_config --name sanity-gravity
```

### `snapshot`

Freeze a running container's state into a new Docker image.

```bash
./sanity-cli snapshot --name sanity-gravity --tag my-state:v1
./sanity-cli snapshot --name sanity-gravity --variant ag-xfce-kasm --tag backup:latest
```

| Flag | Description |
|:-----|:------------|
| `-n, --name` | Project name (default: `sanity-gravity`) |
| `-v, --variant` | Tag to snapshot (optional if only one running) |
| `-t, --tag` | *(required)* Tag for the new image (e.g. `my-backup:v1`) |

---

## Other Commands

### `upgrade`

*(Legacy)* Migrate unmanaged containers from older Sanity-Gravity versions to managed status.

### `test [target]`

Run the pytest integration suite.

```bash
./sanity-cli test                           # Run all tests
./sanity-cli test tests/test_cli_agents.py  # Run specific test file
```

---

## Environment Variables

The following environment variables are passed into the container at runtime:

| Variable | Default | Description |
|:---------|:--------|:------------|
| `HOST_UID` | `1000` | UID for the container user |
| `HOST_GID` | `1000` | GID for the container user's group |
| `HOST_USER` | `developer` | Username created inside the container |
| `HOST_PASSWORD` | `antigravity` | Password for SSH, VNC, and KasmVNC |

These are automatically derived from your host system by `sanity-cli up`.
