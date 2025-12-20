# Sanity-Gravity: The Antigravity Sandbox

**Sanity-Gravity** is a secure, containerized sandbox environment designed specifically for **Agentic AI IDEs** (like Google Antigravity). It minimizes execution risks by confining the agent's activities within a disposable Docker container while providing a full graphical desktop experience.

## Why Sanity-Gravity?

*   **🛡️ Safety First**: Isolates "Agentic Execution" risks. If an agent executes `rm -rf /` or malicious code, only the container is affected, not your host machine.
*   **🖥️ Full Desktop GUI**: Includes **Ubuntu 22.04 + XFCE4** and **KasmVNC**, allowing agents to control a real web browser (Chrome) and GUI applications naturally.
*   **🚀 Zero Config**: Pre-installed with **Antigravity IDE**, Google Chrome, Git, and essential dev tools.
*   **🔌 Seamless IO**: Automatically maps your host user's UID/GID, preventing the common "root-owned files" permission hell when mounting workspaces.

## Quick Start

### Prerequisites
*   Docker & Docker Compose (v2.0+)
*   Python 3.7+ (for `sanity-cli`)
*   *(Optional)* **NVIDIA Container Toolkit** (for GPU acceleration)

### Installation

1.  Clone the repository:
    ```bash
    git clone https://github.com/shiritai/sanity-gravity.git
    cd sanity-gravity
    ```

2.  Build the sandbox environment:
    ```bash
    ./sanity-cli build
    ```

3.  Run the KasmVNC variant (Recommended):
    ```bash
    ./sanity-cli run -v kasm --password mysecret
    ```

4.  **Access the Desktop**:
    Open your browser and navigate to: **[https://localhost:8444](https://localhost:8444)**
    *   **User**: `(Your Host Username)`
    *   **Password**: `mysecret` (or `antigravity` if unspecified)

> **Note**: You may see a "Self-signed certificate" warning. This is normal for a local sandbox; click "Advanced" -> "Proceed".

## CLI Usage (`sanity-cli`)

The project includes a helper script `sanity-cli` to manage the lifecycle:

```bash
./sanity-cli list           # List available variants
./sanity-cli build [name]   # Build specific variant (default: all)
./sanity-cli run -v [name] [options] # Run variant
  # Options:
  #   --password [pwd]    (Set SSH/VNC password, default: antigravity)
  #   --ssh-port [port]   (Default: 2222)
  #   --kasm-port [port]  (Default: 8444)
  #   --vnc-port [port]   (Default: 5901)
  #   --novnc-port [port] (Default: 6901)
  #   --gpu               (Enable NVIDIA GPU support)
  #   --skip-check        (Skip prerequisite checks)

./sanity-cli stop           # Stop all containers
./sanity-cli status         # Check container status
```

## Variants

| Variant    | Tech Stack       | Best For                            | Access                                     |
| :--------- | :--------------- | :---------------------------------- | :----------------------------------------- |
| **`kasm`** | KasmVNC          | **Web-based Desktop (Recommended)** | `https://localhost:8444`                   |
| **`vnc`**  | TigerVNC + noVNC | Legacy VNC clients                  | `localhost:5901` / `http://localhost:6901` |
| **`core`** | SSH Only         | Headless / Terminal agents          | `ssh -p <port> developer@localhost`        |

## SSH Access

All variants, **including GUI variants** (Kasm/VNC), have SSH enabled by default. This enables powerful hybrid workflows:

*   **Headless Control**: Automate GUI tools via CLI without opening the desktop.
*   **Port Forwarding**: Tunnel web apps or debuggers from the container to your host (e.g., `ssh -L 3000:localhost:3000 ...`).
*   **File Transfer**: Easily move build artifacts using `scp` or `sftp`.
*   **Remote Development**: Connect your local VS Code / JetBrains IDE via SSH for a comfortable coding experience while the Agent runs in the sandbox.

**Default Port**: `2222` (Configurable via `--ssh-port`)
**Credentials**: User `(Your Host Username)` / Password `antigravity` (or custom)

```bash
# Example: Connect to Kasm variant
ssh -p 2222 developer@localhost
```

## License

This project is licensed under the **Apache License 2.0**. See [LICENSE](LICENSE) for details.
