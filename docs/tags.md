# Modular Tag System

Every Sanity-Gravity image is described by a **3-dimensional tag**: `{agent}-{desktop}-{connector}`.

## Dimensions

### Agents

The AI tool installed in the sandbox.

| Slug | Name | Tier | Requires GUI | What's Installed |
|:-----|:-----|:-----|:-------------|:-----------------|
| `ag` | Antigravity IDE | official | Yes | Antigravity IDE 2.5.5 (official tarball, pinned by build id and sha256; the browser comes with the desktop) |
| `agy` | Antigravity CLI | official | No | Antigravity CLI (official installer) -- Gemini CLI's official successor |
| `cc` | Claude Code | official | No | Claude Code CLI (official installer) |
| `cx` | OpenAI Codex CLI | official | No | Codex CLI (static musl `codex` binary, official installer) |
| `dsh` | DeepSeek Harness | community | No | DeepSeek Harness `dsh` launcher (hash-pinned PyPI runtime wheel, no Node.js) |
| `gc` | Gemini CLI | deprecated | No | Node.js 22 + `@google/gemini-cli` |
| `oc` | OpenCode | official | No | OpenCode CLI (single Bun-compiled `opencode` binary, official installer) |
| `ocd` | OpenCode Desktop | community | Yes | OpenCode Desktop (Electron GUI app, official .deb for amd64/arm64) |

> **`ag` pins the IDE, and the pin has a deadline.** `ag` installs the standalone Antigravity IDE 2.5.5 from Google's official tarball, pinned by version and build id and verified against the sha256 Google publishes for that exact artifact; auto-update is off, so a sandbox stays on the build it was built with. The 1.x package this replaced is deprecated and its apt repo froze on 2026-04-16 - the language-server certificate 1.x bundles expired on 2026-09-04, and after that every Agent Manager message was stored and never answered, with no error shown ([#42](https://github.com/Shiritai/sanity-gravity/issues/42)). 2.5.5 keeps the same design with a later certificate, valid until **2026-11-03**, so the image build fails on purpose once that is 14 days away; re-check upstream for a newer IDE build before 2026-10-20. Sign-in is in-container: the IDE opens Google's page in the bundled browser and the callback comes back over an `antigravity-ide://` link, which the image registers as a URL handler, so nothing is forwarded from the host.

> **Community tier (`dsh`).** DeepSeek Harness is an upstream developer preview (rc releases only, breaking changes promised), so its ten tags build locally but never enter the CI/publish matrix - `pull` has nothing to fetch, run `./sanity-cli build dsh-none-ssh` first. The single `dsh` launcher serves both profiles: `dsh --profile headless "task"` for one-shot CLI runs, and `dsh web` for the browser UI, which listens on `127.0.0.1:3080` only (upstream refuses `0.0.0.0`) - reach it with `ssh -p 2222 -L 3080:127.0.0.1:3080 <user>@localhost` or the in-container browser every desktop variant ships. **The web UI is broken on the pinned 0.1.5rc1 PyPI wheel**: the packaged runtime drops the `dsh.client` manifests while building its module proxy, so the page loads with zero client packages and shows `Failed to load plugins`; nothing in this image can repair that, so use the headless profile until an upstream PyPI release fixes it (the npm channel is unaffected, but cannot be hash-pinned here). Auth is in-container only: `export DEEPSEEK_API_KEY=...`, put the key in `~/.dsh/.env`, or use the web UI's Settings -> Models; no host key is ever forwarded. See [Support tiers](../CONTRIBUTING.md#support-tiers).

> **`gc` is deprecated.** Google shut down the Gemini CLI free tier on
> 2026-06-18; it now requires a paid Gemini API key / Code Assist license.
> The plugin and its images are kept for those users, but new users should
> prefer **`agy`** (Antigravity CLI), Google's official replacement.

> **Community tier (`ocd`).** Its nine tags build and run locally like any other, but CI never builds them and they are not published to GHCR, so `pull` has nothing to fetch — run `./sanity-cli build ocd-xfce-kasm` first. The app is the Electron GUI, reachable only from the desktop menu of a GUI variant (`xfce`, `lxqt` or `openbox`); there is no `opencode` command on PATH (that is the sibling `oc` plugin). OpenCode's free-tier models are gated server-side to the official harness since 2026-09-17, so they fail inside the sandbox with `Error from provider (Console)` no matter which version is pinned ([anomalyco/opencode#49588](https://github.com/anomalyco/opencode/issues/49588)) - configure your own provider API key in `~/.config/opencode/opencode.json` instead (the entrypoint seed already creates that file). See [Support tiers](../CONTRIBUTING.md#support-tiers).

### Desktops

Whether a graphical desktop environment is included.

| Slug | Name | Tier | Has GUI |
|:-----|:-----|:-----|:--------|
| `xfce` | XFCE | official | Yes — full XFCE4 desktop with window manager; ships a browser |
| `lxqt` | LXQt | community | Yes — LXQt session (`lxqt-core`) with `xfwm4` as the window manager; ships a browser |
| `openbox` | Openbox | community | Yes — window manager only, no panel: the smallest GUI install; ships a browser |
| `none` | Headless | official | No — `DISPLAY` is unset, minimal footprint; no browser |

> **The browser belongs to the desktop.** Each display desktop installs Google Chrome (amd64) or Chromium (arm64) as `x-www-browser` and as what `xdg-open` resolves to, so every tag with a desktop can open a link - whichever agent it carries.

> **Community tier (`lxqt`, `openbox`).** Each of these desktops adds 24 tags that build and run locally like any other, but CI never builds them and they are not published to GHCR, so `pull` has nothing to fetch — run `./sanity-cli build cc-openbox-kasm` first. Twenty-one of each 24 are community through the desktop; the other three are `gc-lxqt-*` and `gc-openbox-*`, deprecated through the agent. See [Support tiers](../CONTRIBUTING.md#support-tiers).

### Connectors

How you connect to the running container.

| Slug | Name | Requires GUI | Ports |
|:-----|:-----|:-------------|:------|
| `kasm` | KasmVNC | Yes | `8444` (HTTPS) |
| `vnc` | TigerVNC + noVNC | Yes | `5901` (VNC), `6901` (noVNC HTTP) |
| `ssh` | SSH only | No | `22` (mapped to host `2222`) |

## Constraint Rules

Not all combinations are valid. Two rules are enforced:

1. **GUI connectors require a GUI desktop**: `kasm` and `vnc` can only pair with `xfce`, `lxqt` or `openbox` (not `none`).
2. **GUI agents require a GUI desktop**: `ag` (Antigravity IDE) and `ocd` (OpenCode Desktop) can only pair with `xfce`, `lxqt` or `openbox` (not `none`).

These rules are enforced by `sanity-cli` at build time and run time.

## All Valid Tags (78)

Listed in the same order as `./sanity-cli list` (agents sorted alphabetically).

| Tag | Agent | Desktop | Connector | Use Case |
|:----|:------|:--------|:----------|:---------|
| `ag-lxqt-kasm` * | Antigravity | LXQt | KasmVNC | Full IDE sandbox via browser |
| `ag-lxqt-ssh` * | Antigravity | LXQt | SSH | Full IDE sandbox, SSH-only access |
| `ag-lxqt-vnc` * | Antigravity | LXQt | TigerVNC | Full IDE sandbox via legacy VNC client |
| `ag-openbox-kasm` * | Antigravity | Openbox | KasmVNC | Full IDE sandbox via browser |
| `ag-openbox-ssh` * | Antigravity | Openbox | SSH | Full IDE sandbox, SSH-only access |
| `ag-openbox-vnc` * | Antigravity | Openbox | TigerVNC | Full IDE sandbox via legacy VNC client |
| **`ag-xfce-kasm`** | Antigravity | XFCE | KasmVNC | Full IDE sandbox via browser **(default)** |
| `ag-xfce-ssh` | Antigravity | XFCE | SSH | Full IDE sandbox, SSH-only access |
| `ag-xfce-vnc` | Antigravity | XFCE | TigerVNC | Full IDE sandbox via legacy VNC client |
| `agy-lxqt-kasm` * | Antigravity CLI | LXQt | KasmVNC | Antigravity CLI with LXQt desktop |
| `agy-lxqt-ssh` * | Antigravity CLI | LXQt | SSH | Antigravity CLI with GUI, SSH-only access |
| `agy-lxqt-vnc` * | Antigravity CLI | LXQt | TigerVNC | Antigravity CLI with legacy VNC |
| `agy-none-ssh` | Antigravity CLI | Headless | SSH | Lightweight Antigravity CLI terminal |
| `agy-openbox-kasm` * | Antigravity CLI | Openbox | KasmVNC | Antigravity CLI with Openbox desktop |
| `agy-openbox-ssh` * | Antigravity CLI | Openbox | SSH | Antigravity CLI with GUI, SSH-only access |
| `agy-openbox-vnc` * | Antigravity CLI | Openbox | TigerVNC | Antigravity CLI with legacy VNC |
| `agy-xfce-kasm` | Antigravity CLI | XFCE | KasmVNC | Antigravity CLI with browser desktop |
| `agy-xfce-ssh` | Antigravity CLI | XFCE | SSH | Antigravity CLI with GUI, SSH-only access |
| `agy-xfce-vnc` | Antigravity CLI | XFCE | TigerVNC | Antigravity CLI with legacy VNC |
| `cc-lxqt-kasm` * | Claude Code | LXQt | KasmVNC | Claude Code with LXQt desktop |
| `cc-lxqt-ssh` * | Claude Code | LXQt | SSH | Claude Code with GUI, SSH-only access |
| `cc-lxqt-vnc` * | Claude Code | LXQt | TigerVNC | Claude Code with legacy VNC |
| `cc-none-ssh` | Claude Code | Headless | SSH | Lightweight Claude Code terminal |
| `cc-openbox-kasm` * | Claude Code | Openbox | KasmVNC | Claude Code with Openbox desktop |
| `cc-openbox-ssh` * | Claude Code | Openbox | SSH | Claude Code with GUI, SSH-only access |
| `cc-openbox-vnc` * | Claude Code | Openbox | TigerVNC | Claude Code with legacy VNC |
| `cc-xfce-kasm` | Claude Code | XFCE | KasmVNC | Claude Code with browser desktop |
| `cc-xfce-ssh` | Claude Code | XFCE | SSH | Claude Code with GUI, SSH-only access |
| `cc-xfce-vnc` | Claude Code | XFCE | TigerVNC | Claude Code with legacy VNC |
| `cx-lxqt-kasm` * | OpenAI Codex | LXQt | KasmVNC | Codex with LXQt desktop |
| `cx-lxqt-ssh` * | OpenAI Codex | LXQt | SSH | Codex with GUI, SSH-only access |
| `cx-lxqt-vnc` * | OpenAI Codex | LXQt | TigerVNC | Codex with legacy VNC |
| `cx-none-ssh` | OpenAI Codex | Headless | SSH | Lightweight Codex terminal |
| `cx-openbox-kasm` * | OpenAI Codex | Openbox | KasmVNC | Codex with Openbox desktop |
| `cx-openbox-ssh` * | OpenAI Codex | Openbox | SSH | Codex with GUI, SSH-only access |
| `cx-openbox-vnc` * | OpenAI Codex | Openbox | TigerVNC | Codex with legacy VNC |
| `cx-xfce-kasm` | OpenAI Codex | XFCE | KasmVNC | Codex with browser desktop |
| `cx-xfce-ssh` | OpenAI Codex | XFCE | SSH | Codex with GUI, SSH-only access |
| `cx-xfce-vnc` | OpenAI Codex | XFCE | TigerVNC | Codex with legacy VNC |
| `dsh-lxqt-kasm` * | DeepSeek Harness | LXQt | KasmVNC | Harness with LXQt desktop |
| `dsh-lxqt-ssh` * | DeepSeek Harness | LXQt | SSH | Harness with GUI, SSH-only access |
| `dsh-lxqt-vnc` * | DeepSeek Harness | LXQt | TigerVNC | Harness with legacy VNC |
| `dsh-none-ssh` * | DeepSeek Harness | Headless | SSH | Lightweight harness terminal (headless profile) |
| `dsh-openbox-kasm` * | DeepSeek Harness | Openbox | KasmVNC | Harness with Openbox desktop |
| `dsh-openbox-ssh` * | DeepSeek Harness | Openbox | SSH | Harness with GUI, SSH-only access |
| `dsh-openbox-vnc` * | DeepSeek Harness | Openbox | TigerVNC | Harness with legacy VNC |
| `dsh-xfce-kasm` * | DeepSeek Harness | XFCE | KasmVNC | Harness with XFCE desktop |
| `dsh-xfce-ssh` * | DeepSeek Harness | XFCE | SSH | Harness with GUI, SSH-only access |
| `dsh-xfce-vnc` * | DeepSeek Harness | XFCE | TigerVNC | Harness with legacy VNC |
| `gc-lxqt-kasm` | Gemini CLI | LXQt | KasmVNC | Gemini with LXQt desktop |
| `gc-lxqt-ssh` | Gemini CLI | LXQt | SSH | Gemini with GUI, SSH-only access |
| `gc-lxqt-vnc` | Gemini CLI | LXQt | TigerVNC | Gemini with legacy VNC |
| `gc-none-ssh` | Gemini CLI | Headless | SSH | Lightweight Gemini terminal |
| `gc-openbox-kasm` | Gemini CLI | Openbox | KasmVNC | Gemini with Openbox desktop |
| `gc-openbox-ssh` | Gemini CLI | Openbox | SSH | Gemini with GUI, SSH-only access |
| `gc-openbox-vnc` | Gemini CLI | Openbox | TigerVNC | Gemini with legacy VNC |
| `gc-xfce-kasm` | Gemini CLI | XFCE | KasmVNC | Gemini with browser desktop |
| `gc-xfce-ssh` | Gemini CLI | XFCE | SSH | Gemini with GUI, SSH-only access |
| `gc-xfce-vnc` | Gemini CLI | XFCE | TigerVNC | Gemini with legacy VNC |
| `oc-lxqt-kasm` * | OpenCode | LXQt | KasmVNC | OpenCode with LXQt desktop |
| `oc-lxqt-ssh` * | OpenCode | LXQt | SSH | OpenCode with GUI, SSH-only access |
| `oc-lxqt-vnc` * | OpenCode | LXQt | TigerVNC | OpenCode with legacy VNC |
| `oc-none-ssh` | OpenCode | Headless | SSH | Lightweight OpenCode terminal |
| `oc-openbox-kasm` * | OpenCode | Openbox | KasmVNC | OpenCode with Openbox desktop |
| `oc-openbox-ssh` * | OpenCode | Openbox | SSH | OpenCode with GUI, SSH-only access |
| `oc-openbox-vnc` * | OpenCode | Openbox | TigerVNC | OpenCode with legacy VNC |
| `oc-xfce-kasm` | OpenCode | XFCE | KasmVNC | OpenCode with browser desktop |
| `oc-xfce-ssh` | OpenCode | XFCE | SSH | OpenCode with GUI, SSH-only access |
| `oc-xfce-vnc` | OpenCode | XFCE | TigerVNC | OpenCode with legacy VNC |
| `ocd-lxqt-kasm` * | OpenCode Desktop | LXQt | KasmVNC | OpenCode Desktop with LXQt desktop |
| `ocd-lxqt-ssh` * | OpenCode Desktop | LXQt | SSH | OpenCode Desktop with GUI, SSH-only access |
| `ocd-lxqt-vnc` * | OpenCode Desktop | LXQt | TigerVNC | OpenCode Desktop with legacy VNC |
| `ocd-openbox-kasm` * | OpenCode Desktop | Openbox | KasmVNC | OpenCode Desktop with Openbox desktop |
| `ocd-openbox-ssh` * | OpenCode Desktop | Openbox | SSH | OpenCode Desktop with GUI, SSH-only access |
| `ocd-openbox-vnc` * | OpenCode Desktop | Openbox | TigerVNC | OpenCode Desktop with legacy VNC |
| `ocd-xfce-kasm` * | OpenCode Desktop | XFCE | KasmVNC | OpenCode Desktop with browser desktop |
| `ocd-xfce-ssh` * | OpenCode Desktop | XFCE | SSH | OpenCode Desktop with GUI, SSH-only access |
| `ocd-xfce-vnc` * | OpenCode Desktop | XFCE | TigerVNC | OpenCode Desktop with legacy VNC |

\* Community tier: build locally with `./sanity-cli build <tag>`; not published to GHCR, so `pull` has nothing to fetch.

## Discovery Commands

```bash
# List all valid tags with dimension info
./sanity-cli list

# Output as JSON array (for CI matrix)
./sanity-cli list --json
```
