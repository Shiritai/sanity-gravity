# Sanity-Gravity: The Antigravity Sandbox

<p align="center">
  <img src="assets/logo.jpg" alt="Sanity-Gravity Logo" width="300">
</p>

<p align="center">
  <em>A containerized sandbox for Agentic AI — full desktop, headless CLI, or SSH-only, in seconds.</em>
</p>

<p align="center">
  <a href="README.md">English</a> | <a href="README_zh-TW.md">繁體中文</a> | <a href="README_ja.md">日本語</a>
</p>

<p align="center">
  <a href="https://github.com/shiritai/sanity-gravity/actions"><img src="https://github.com/shiritai/sanity-gravity/actions/workflows/ci-pr.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache_2.0-blue.svg" alt="License"></a>
</p>

## Prerequisites

* Docker & Docker Compose (v2.0+)
* Python 3.7+
* **Tested on**: Ubuntu (amd64/arm64), macOS (Apple Silicon)

## TL;DR

```bash
# 1. Clone
git clone https://github.com/shiritai/sanity-gravity.git
cd sanity-gravity

# 2. Build the images (one-time)
./sanity-cli build

# 3. Launch the recommended sandbox
./sanity-cli up -v ag-xfce-kasm --password mysecret
```

Open **https://localhost:8444** — your sandboxed desktop is ready!

* **Username**: your host OS username
* **Password**: `mysecret` (default: `antigravity`)

> The self-signed certificate warning on localhost is expected. Click through it.

## Why Sanity-Gravity?

AI agents run arbitrary code. One rogue `rm -rf /` and your host is toast. Sanity-Gravity confines every agent action inside a disposable Docker container while streaming a full desktop experience to your browser — or providing just a minimal SSH shell when that's all you need.

| Feature                        | Description                                                                                                       |
| :----------------------------- | :---------------------------------------------------------------------------------------------------------------- |
| **Host Isolation**             | Even if an agent runs `rm -rf /` or downloads malware, only the sandbox is destroyed. Your host stays untouched.  |
| **Full GUI Desktop**           | Ubuntu 24.04 + XFCE4 + KasmVNC. Agents operate browsers and GUI apps just like a human would.                    |
| **Headless CLI Agents**        | Minimal images for Gemini CLI and Claude Code — no desktop overhead, just SSH.                                    |
| **Out-of-the-Box**             | Pre-installed with Antigravity IDE, Google Chrome, and Git. Zero setup time.                                      |
| **Seamless Disk I/O**          | Smart UID/GID mapping. No root-owned file disasters after host volume mounts.                                     |
| **Multi-Instance**             | Parallel isolated sandboxes. Host ports are auto-allocated when unspecified (zero conflicts), or can be set manually. |
| **Container Snapshots**        | Freeze your configured environment (installed software, active logins) into a new image branch.                   |
| **IDE Safe Upgrade**           | Built-in `dpkg-divert` protection prevents `apt upgrade` from breaking Antigravity or Chrome.                     |
| **SSH Agent Proxy**            | Use host SSH keys inside containers — no private key copying required.                                            |
| **Multi-Arch**                 | All images support both `amd64` and `arm64`.                                                                      |

📺 **[Watch Demo on YouTube](https://youtu.be/x0DGKuHyx2A)**

## Choose Your Sandbox

Every image is described by a tag: **`{agent}-{desktop}-{connector}`**. Pick one that matches your use case:

| I want to...                     | Tag              | Connect via                |
| :------------------------------- | :--------------- | :------------------------- |
| Run Antigravity IDE in browser   | `ag-xfce-kasm`   | `https://localhost:8444`   |
| Run Antigravity IDE via VNC      | `ag-xfce-vnc`    | `localhost:5901`           |
| Use Gemini CLI in a terminal     | `gc-none-ssh`    | `ssh -p 2222 ...`         |
| Use Gemini CLI with a desktop    | `gc-xfce-kasm`   | `https://localhost:8444`   |
| Use Claude Code in a terminal    | `cc-none-ssh`    | `ssh -p 2222 ...`         |
| Use Claude Code with a desktop   | `cc-xfce-kasm`   | `https://localhost:8444`   |

> **First time?** Start with **`ag-xfce-kasm`** — it gives you the full desktop experience via your browser.

There are **11 valid combinations** in total. See [Modular Tag System](docs/tags.md) for the full matrix, dimension model, and constraint rules.

## Command Reference

### Lifecycle

```bash
./sanity-cli up -v <tag>        # Start a sandbox
  --password <pwd>              #   SSH/VNC password (default: antigravity)
  --workspace <path>            #   Host directory to mount (default: ./workspace)
  --name <name>                 #   Project name for multi-instance (default: sanity-gravity)
  --cpus <n> --memory <n>       #   Resource limits (e.g. --cpus 2 --memory 4G)
  --image <img>                 #   Use a snapshot image instead of the default

./sanity-cli down               # Stop and remove containers
./sanity-cli stop / start       # Pause / resume
./sanity-cli restart            # Force restart
./sanity-cli clean              # Deep cleanup: containers, volumes, and local images
```

### Inspection

```bash
./sanity-cli status             # Show running instances
./sanity-cli shell              # Drop into container shell (zsh, fallback to bash)
  --use {zsh,bash}              #   Pick shell explicitly (disables fallback)
./sanity-cli open               # Open web desktop in browser
```

### Build

```bash
./sanity-cli build [tag...]     # Build images (default: all)
  --no-cache                    #   Disable Docker layer cache
./sanity-cli list               # Show all valid tags
./sanity-cli list --json        # JSON output (for CI matrix)
./sanity-cli check              # Verify Docker prerequisites
```

Full reference with all flags and environment variables: [CLI Reference](docs/cli-reference.md)

## Advanced Features

### IDE Management & Safe Upgrade

Sanity-Gravity provides a robust defense mechanism against accidental IDE or browser uninstallation caused by `apt upgrade`.

- **Host side**: `sanity-cli` manages container lifecycles. Maintenance commands **auto-inject the latest protection script** into the target container, ensuring backward compatibility with legacy snapshots.
- **Container side**: `gravity-cli` (built-in) safely manages Antigravity IDE and Google Chrome via `dpkg-divert`, guaranteeing their `--no-sandbox` privilege protections survive system updates.

#### From the Host

```bash
# Safely update IDE to the latest package version
./sanity-cli ide update --name sanity-gravity

# Nuclear option: full wipe + clean reinstall to fix persistent crashes
./sanity-cli ide reinstall --name sanity-gravity
```

#### Inside the Container

```bash
sudo gravity-cli update-ide     # Equivalent to 'ide update'
sudo gravity-cli reinstall-ide  # Equivalent to 'ide reinstall'
```

### SSH Agent Proxy

A built-in proxy bridges your host's SSH Agent Socket into the container. This enables `git push` / `git pull` inside the sandbox using your host's private keys — without ever copying them.

`./sanity-cli up` handles this automatically. For manual control:

```bash
./sanity-cli proxy status       # Check proxy and active connections
./sanity-cli proxy setup        # Restart / fix proxy
./sanity-cli proxy remove       # Terminate proxy
```

### Multi-Instance

Run unlimited parallel sandboxes using `--name`:

```bash
# Launch a second instance
./sanity-cli up -v ag-xfce-kasm --name dev-02 --workspace /tmp/dev02
```

**Zero-Conflict Guarantee**: `sanity-cli` auto-allocates free host ports when using a custom name. Check your assigned ports via `./sanity-cli status`. Target a specific instance with `--name` (e.g. `./sanity-cli down --name dev-02`).

### Container Snapshots

Freeze your configured environment — installed software, login sessions, custom settings — into a reusable image.

1. **Create a snapshot**:
   ```bash
   ./sanity-cli snapshot --name my-base-env --tag my-verified-state:v1
   ```

2. **Launch from the snapshot**:
   ```bash
   ./sanity-cli up -v ag-xfce-kasm --name new-experiment --image my-verified-state:v1
   ```

## SSH Access

All images — including GUI variants — expose SSH on port `2222` by default. This enables:

- **Headless automation** — script tasks from the host without opening a desktop
- **Port forwarding** — `ssh -L 3000:localhost:3000 -p 2222 $USER@localhost`
- **Remote development** — VS Code Remote SSH, JetBrains Gateway

```bash
ssh -p 2222 $USER@localhost
```

## Project Structure

```
sanity-gravity/
├── sanity-cli                  # CLI entry point (Python 3, no external deps)
├── sandbox/
│   ├── Dockerfile.base         # Base layer: Ubuntu 24.04 + SSH + supervisord
│   ├── layers/
│   │   ├── desktops/           # xfce, none
│   │   ├── agents/             # ag (Antigravity), gc (Gemini CLI), cc (Claude Code)
│   │   └── connectors/         # kasm (KasmVNC), vnc (TigerVNC), ssh
│   └── rootfs/                 # Shared overlay (entrypoint, gravity-cli, supervisor configs)
├── lib/                        # Proxy manager module
├── config/                     # Runtime-generated docker-compose files (git-ignored)
├── tests/                      # Pytest integration suite
├── workspace/                  # Default bind-mounted workspace
└── .github/workflows/          # CI/CD pipelines
```

For details on the 4-layer FROM-chained build system and CI architecture, see [Architecture](docs/architecture.md) and [CI/CD](docs/ci-cd.md).

## What's in a Name?

> **"Sanity-Gravity"** — providing a strong **Gravity** (constraints) in the unpredictable world of **Antigravity** (AI agents), to preserve the developer's **Sanity**.

By confining unvetted AI execution to disposable containers, we eliminate irreversible damage: accidental file deletion, credential hijacking, configuration pollution.

## License

[Apache License 2.0](LICENSE)
