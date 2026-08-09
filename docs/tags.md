# Modular Tag System

Every Sanity-Gravity image is described by a **3-dimensional tag**: `{agent}-{desktop}-{connector}`.

## Dimensions

### Agents

The AI tool installed in the sandbox.

| Slug | Name | Requires GUI | What's Installed |
|:-----|:-----|:-------------|:-----------------|
| `ag` | Antigravity IDE | Yes | Antigravity IDE + Google Chrome |
| `agy` | Antigravity CLI | No | Antigravity CLI (official installer) -- Gemini CLI's official successor |
| `cc` | Claude Code | No | Claude Code CLI (official installer) |
| `cx` | OpenAI Codex CLI | No | Codex CLI (static musl `codex` binary, official installer) |
| `gc` | Gemini CLI **(deprecated)** | No | Node.js 22 + `@google/gemini-cli` |
| `oc` | OpenCode | No | OpenCode CLI (single Bun-compiled `opencode` binary, official installer) |
| `od` | OpenCode Desktop | Yes | OpenCode Desktop (Electron GUI app, official .deb for amd64/arm64) |

> **`gc` is deprecated.** Google shut down the Gemini CLI free tier on
> 2026-06-18; it now requires a paid Gemini API key / Code Assist license.
> The plugin and its images are kept for those users, but new users should
> prefer **`agy`** (Antigravity CLI), Google's official replacement.

### Desktops

Whether a graphical desktop environment is included.

| Slug | Name | Has GUI |
|:-----|:-----|:--------|
| `xfce` | XFCE | Yes — full XFCE4 desktop with window manager |
| `none` | Headless | No — `DISPLAY` is unset, minimal footprint |

### Connectors

How you connect to the running container.

| Slug | Name | Requires GUI | Ports |
|:-----|:-----|:-------------|:------|
| `kasm` | KasmVNC | Yes | `8444` (HTTPS) |
| `vnc` | TigerVNC + noVNC | Yes | `5901` (VNC), `6901` (noVNC HTTP) |
| `ssh` | SSH only | No | `22` (mapped to host `2222`) |

## Constraint Rules

Not all combinations are valid. Two rules are enforced:

1. **GUI connectors require a GUI desktop**: `kasm` and `vnc` can only pair with `xfce` (not `none`).
2. **GUI agents require a GUI desktop**: `ag` (Antigravity IDE) and `od` (OpenCode Desktop) can only pair with `xfce` (not `none`).

These rules are enforced by `sanity-cli` at build time and run time.

## All Valid Tags (26)

Listed in the same order as `./sanity-cli list` (agents sorted alphabetically).

| Tag | Agent | Desktop | Connector | Use Case |
|:----|:------|:--------|:----------|:---------|
| **`ag-xfce-kasm`** | Antigravity | XFCE | KasmVNC | Full IDE sandbox via browser **(default)** |
| `ag-xfce-ssh` | Antigravity | XFCE | SSH | Full IDE sandbox, SSH-only access |
| `ag-xfce-vnc` | Antigravity | XFCE | TigerVNC | Full IDE sandbox via legacy VNC client |
| `agy-none-ssh` | Antigravity CLI | Headless | SSH | Lightweight Antigravity CLI terminal |
| `agy-xfce-kasm` | Antigravity CLI | XFCE | KasmVNC | Antigravity CLI with browser desktop |
| `agy-xfce-ssh` | Antigravity CLI | XFCE | SSH | Antigravity CLI with GUI, SSH-only access |
| `agy-xfce-vnc` | Antigravity CLI | XFCE | TigerVNC | Antigravity CLI with legacy VNC |
| `cc-none-ssh` | Claude Code | Headless | SSH | Lightweight Claude Code terminal |
| `cc-xfce-kasm` | Claude Code | XFCE | KasmVNC | Claude Code with browser desktop |
| `cc-xfce-ssh` | Claude Code | XFCE | SSH | Claude Code with GUI, SSH-only access |
| `cc-xfce-vnc` | Claude Code | XFCE | TigerVNC | Claude Code with legacy VNC |
| `cx-none-ssh` | OpenAI Codex | Headless | SSH | Lightweight Codex terminal |
| `cx-xfce-kasm` | OpenAI Codex | XFCE | KasmVNC | Codex with browser desktop |
| `cx-xfce-ssh` | OpenAI Codex | XFCE | SSH | Codex with GUI, SSH-only access |
| `cx-xfce-vnc` | OpenAI Codex | XFCE | TigerVNC | Codex with legacy VNC |
| `gc-none-ssh` | Gemini CLI | Headless | SSH | Lightweight Gemini terminal |
| `gc-xfce-kasm` | Gemini CLI | XFCE | KasmVNC | Gemini with browser desktop |
| `gc-xfce-ssh` | Gemini CLI | XFCE | SSH | Gemini with GUI, SSH-only access |
| `gc-xfce-vnc` | Gemini CLI | XFCE | TigerVNC | Gemini with legacy VNC |
| `oc-none-ssh` | OpenCode | Headless | SSH | Lightweight OpenCode terminal |
| `oc-xfce-kasm` | OpenCode | XFCE | KasmVNC | OpenCode with browser desktop |
| `oc-xfce-ssh` | OpenCode | XFCE | SSH | OpenCode with GUI, SSH-only access |
| `oc-xfce-vnc` | OpenCode | XFCE | TigerVNC | OpenCode with legacy VNC |
| `od-xfce-kasm` | OpenCode Desktop | XFCE | KasmVNC | OpenCode Desktop with browser desktop |
| `od-xfce-ssh` | OpenCode Desktop | XFCE | SSH | OpenCode Desktop with GUI, SSH-only access |
| `od-xfce-vnc` | OpenCode Desktop | XFCE | TigerVNC | OpenCode Desktop with legacy VNC |

## Discovery Commands

```bash
# List all valid tags with dimension info
./sanity-cli list

# Output as JSON array (for CI matrix)
./sanity-cli list --json
```
