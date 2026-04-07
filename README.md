# Sanity-Gravity: The Antigravity Sandbox

<p align="center">
  <img src="assets/logo.jpg" alt="Sanity-Gravity Logo" width="300">
</p>

<p align="center">
  <em>A modernized, secured container sandbox environment built perfectly for Agentic AI IDEs</em>
</p>

<p align="center">
  <a href="README.md">English</a> | <a href="README_zh-TW.md">繁體中文</a> | <a href="README_ja.md">日本語</a>
</p>

---

## TL;DR

**Sanity-Gravity** is a modern, zero-configuration GUI sandbox tailored for Antigravity workflows. It completely confines all potentially high-risk actions into disposable Docker containers while seamlessly streaming a full XFCE4 desktop experience to your browser.

**Spin up a secure Antigravity development environment in seconds:**

```bash
# 1. Build the base images
./sanity-cli build

# 2. Start the sandbox with a persistent workspace volume
./sanity-cli up -v kasm --name my-agent-task --workspace ./ai-workspace
```

Your secure desktop is ready, go to **https://localhost:8444**!
- **Username**: `(Your actual Host OS username)`
- **Password**: `antigravity` (Or whatever you set via `--password`)

📺 **[Watch Demo on YouTube](https://youtu.be/x0DGKuHyx2A)**

## Table of Contents

- [Why Sanity-Gravity?](#why-sanity-gravity)
- [Quick Start](#quick-start)
- [Command Reference (`sanity-cli`)](#command-reference-sanity-cli)
- [Advanced Features](#advanced-features)
  - [IDE Management & Safe Upgrade](#ide-management--safe-upgrade-gravity-cli)
  - [Multi-Instance Support](#multi-instance-support)
  - [Container Snapshots](#container-snapshots-perfect-copy)
  - [SSH Agent Proxy](#ssh-agent-proxy-advanced)
  - [Runtime Config Sync](#runtime-config-sync)
- [Variants](#variants)
- [SSH Access](#ssh-access)
- [Project Structure](#project-structure)
- [What's in a Name?](#whats-in-a-name)

---

## Why Sanity-Gravity?

| Feature                 | Description                                                                                                            |
| :---------------------- | :--------------------------------------------------------------------------------------------------------------------- |
| **🛡️ Absolute Safety**   | Completely shields the host. Even if an AI agent runs `rm -rf /` or downloads malware, only the sandbox is destroyed.  |
| **🖥️ Full GUI Desktop**  | Built-in **Ubuntu 24.04 + XFCE4** and **KasmVNC**. AI agents can operate browsers and GUI interfaces just like humans. |
| **🚀 Out-of-the-Box**    | Pre-installed with **Antigravity IDE**, Google Chrome, Git, etc. Zero setup time required.                             |
| **🔌 Seamless Disk I/O** | Smartly maps to your host's UID/GID. No more root-owned file disasters after host volume mounts.                       |
| **🧩 Multi-Instance**    | Parallelize tasks with isolated sandboxes. The system automatically assigns clean ports avoiding conflicts.            |
| **📸 Freeze Snapshots**  | Quickly freeze the customized environment state (installed software, active logins) into a new image branch.           |
| **🔄 IDE Safe Upgrade**  | Built-in scripts manage Agentic IDE updates remotely, strictly bypassing destructive `apt upgrade` behaviors.          |
| **🔑 SSH Agent Proxy**   | Securely pass host SSH credentials to the container. Execute Git operations freely without copying private keys.       |

## Quick Start

### System Requirements
* Docker & Docker Compose (v2.0+)
* Python 3.7+ (Powers `sanity-cli`)
* *(Optional)* **NVIDIA Container Toolkit** (For GPU Support)
* **Supported Environments**: Extensively tested and verified on **Ubuntu (amd64/arm64)** and **macOS 26.0.1 (Apple Silicon M1)**.

### Installation

1. Clone this repository:
   ```bash
   git clone https://github.com/shiritai/sanity-gravity.git
   cd sanity-gravity
   ```

2. Build your sandbox base images:
   ```bash
   ./sanity-cli build
   ```

3. Launch the KasmVNC variant (Recommended for a smooth web experience):
   ```bash
   ./sanity-cli up -v kasm --password mysecret
   ```

4. **Access your desktop**:
   Open a browser and navigate to: **[https://localhost:8444](https://localhost:8444)**
   * **Username**: `(Your host username)`
   * **Password**: `mysecret` (Default is `antigravity`)

> **Note**: A "Self-Signed Certificate" warning is completely normal on localhost. Click "Advanced" and proceed.

## Command Reference (`sanity-cli`)

`sanity-cli` acts as the central orchestrator providing the following commands:

```bash
# Lifecycle Management
./sanity-cli up -v [name]   # Start container (options below)
  --password [pwd]          # Custom SSH/VNC password (default: antigravity)
  --workspace [path]        # Assign workspace dir (default: ./workspace)
  --name [name]             # Isolate instances by project name (default: sanity-gravity)
  --cpus [limit]            # CPU quota (e.g. 1.5)
  --memory [limit]          # Memory quota (e.g. 4G)
  --gpu                     # Enable GPU passthrough
./sanity-cli down           # Stop and entirely delete containers & networks
./sanity-cli stop           # Pause containers (keeps data intact)
./sanity-cli start          # Start paused containers
./sanity-cli restart        # Force reboot running containers

# Environment Inspection
./sanity-cli status         # Check all running instances
./sanity-cli shell          # Instantly drop into a container shell (zsh)
./sanity-cli open           # Launch the default browser to the web VNC

# Maintenance & Sync
./sanity-cli ide <action>   # Remotely deploy IDE maintenance to containers
./sanity-cli proxy <action> # Manage SSH Proxy Daemon service
./sanity-cli sync_config    # Push updated host settings to running containers
./sanity-cli snapshot       # Freeze container state to a new localized image
```

---

## Advanced Features

### 🛠 IDE Management & Safe Upgrade (Gravity-CLI)

Sanity-Gravity provides a robust OS-level defense mechanism against accidental IDE or Web Browser uninstallation / crashes caused by `apt upgrade`.

We strongly separate host orchestration vs container software management:
- **Host**: `sanity-cli` acts as the orchestrator. When executing maintenance commands, it **automatically hot-injects** the latest protection script into the target container, ensuring resilient backward compatibility with all legacy snapshots.
- **Inside**: `gravity-cli` (built-in container script) safely manages the Antigravity IDE and Google Chrome browser via `dpkg-divert`, guaranteeing their `--no-sandbox` privilege protections are never eradicated by subsequent system upgrades.

#### From the Host (Using Sanity-CLI)
If you experience IDE crashes or just want to safely update the underlying Antigravity core, use the remote `ide` command from your host.
> **Note**: Find your running instance `--name` through `./sanity-cli status`.

```bash
# Safely update the Antigravity IDE to the latest package version
./sanity-cli ide update --name sanity-gravity

# Nuclear Option: Complete wipe and clean reinstall to fix persistent crashes
./sanity-cli ide reinstall --name sanity-gravity
```
*(These commands automatically invoke the gravity-cli script as root, keeping all protection and upgrade procedures entirely within the container to maintain a pristine host environment.)*

#### Inside the Container (Using Gravity-CLI)
If you are already inside the container shell (via `./sanity-cli shell`), directly use the CLI. Note that you must be `root`.

```bash
sudo gravity-cli update-ide    # Equivalent to 'ide update'
sudo gravity-cli reinstall-ide # Equivalent to 'ide reinstall'
```

### 🔌 SSH Agent Proxy (Advanced)

Sanity-Gravity includes a smart Proxy Manager that securely bridges the SSH Agent Socket between your host and the container. This enables `git push` / `git pull` operations inside the container using your host's private keys without ever copying them.

Usually `./sanity-cli up` handles everything automatically. For manual interventions:
```bash
./sanity-cli proxy status   # Check Proxy daemon and active connections
./sanity-cli proxy setup    # Restart / fix Proxy daemon
./sanity-cli proxy remove   # Terminate Proxy daemon completely
```

### 🧩 Multi-Instance Support

**Executing parallel tasks?** Run infinite isolated sandbox instances simultaneously using the `--name` argument.

```bash
# Start a second instance named 'dev-02'
./sanity-cli up -v core --name dev-02 --workspace /tmp/dev02
```
**Zero Conflict Guarantee**: `sanity-cli` auto-detects and allocates random available host ports when using a custom name. Read the CLI output to find your assigned ports. Control your instance targeting the given name (e.g., `./sanity-cli down --name dev-02`).

### 📸 Container Snapshots (Perfect Copy)

"Freeze" your configured environment (software installations, active login sessions) into a new image and use it as a base.

1. **Create Snapshot**:
   ```bash
   ./sanity-cli snapshot --name my-base-env --tag my-verified-state:v1
   ```
2. **Use Snapshot**:
   ```bash
   ./sanity-cli up -v kasm --name new-experiment --image my-verified-state:v1
   ```

### 🔄 Runtime Config Sync
If you updated `host_config.py` but don't want to restart the container, simply run `./sanity-cli sync_config` to instantly apply your new Git identities.

---

## Variants

| Variant    | Tech Stack       | Best For                            | Access                                     |
| :--------- | :--------------- | :---------------------------------- | :----------------------------------------- |
| **`kasm`** | KasmVNC          | **Web-based Desktop (Recommended)** | `https://localhost:8444`                   |
| **`vnc`**  | TigerVNC + noVNC | Legacy VNC clients                  | `localhost:5901` / `http://localhost:6901` |
| **`core`** | SSH Only         | Headless / Terminal agents          | `ssh -p <port> developer@localhost`        |

## SSH Access

All variants, **including GUI variants** (Kasm/VNC), have SSH enabled by default (`Port 2222`). This empowers headless task automations, direct port-forwardings (`-L`), SCP commands, and remote logic using VS Code Remote.

```bash
# Example
ssh -p 2222 developer@localhost
```

## Project Structure

```text
sanity-gravity/
├── sanity-cli          # 🛠️ Main CLI entry point (Python script)
├── sandbox/            # 📦 Docker build context and configurations
│   ├── variants/       #    - Dockerfiles for variants (core, kasm, vnc)
│   └── rootfs/         #    - Shared overlay (scripts, configs)
├── tests/              # 🧪 Pytest integration suite
├── workspace/          # 📂 Default mounted user directory
└── .github/            # 🐙 CI/CD & GitHub assets
```

## What's in a Name?

> **"Sanity-Gravity"** implies: Providing a strong **Gravity** (constraints & grounding) in the wild world of **Antigravity** (AI Agents), to preserve the developer's **Sanity**.

By confining unpredictable AI execution to a disposable container, we stop accidental commands (e.g., `rm -rf /`) and configuration pollution.

## License
Apache License 2.0
