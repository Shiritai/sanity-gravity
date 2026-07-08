# Bring Your Own Agent

Sanity-Gravity discovers agents from the plugin tree at startup. Adding an
agent is **a directory + two files** — zero Python, no kernel edits:

```text
plugins/agents/<slug>/
├── manifest.toml    # identity, capabilities, tier, build artifact
└── Dockerfile       # how the agent CLI gets installed
```

Drop them in, and `list` / `build` / `up` / `pull` / port allocation all pick
the new agent up automatically. This guide uses the real `oc` (OpenCode)
agent as the running example — copy it, rename the slug, swap the install
command.

## 1. The manifest

`plugins/agents/oc/manifest.toml`:

```toml
[plugin]
slug = "oc"            # tag dimension: the `oc` in oc-none-ssh
name = "opencode-cli"  # human-readable name shown by `list`
kind = "agent"
api_version = "1"
# tier = "community"   # optional -- see "Support tiers" below

[capabilities]
provides = []
requires = []

[build]
dockerfile = "Dockerfile"
```

Field notes:

- **slug** — short and unique; it becomes the first dimension of every tag
  (`{agent}-{desktop}-{connector}`). Existing agents use 2-3 characters.
- **capabilities** — a pure CLI agent leaves both lists empty; the registry
  then emits every desktop/connector combination that satisfies the display
  rule (four tags today: `<slug>-none-ssh` and `<slug>-xfce-{kasm,vnc,ssh}`).
  An agent that needs a GUI declares `requires = ["display"]` (see
  `plugins/agents/ag/`), which drops the headless variants.
- **No host secrets** — agents declare no `[environment]` entries that leak
  host API keys into the sandbox. Authentication happens in-container (e.g.
  `opencode auth login`, `codex login`).
- **Optional sections** — any plugin may also declare `[ports.<label>]`,
  `[compose]`, `[environment]`, and `[announce]`; agents that provide the
  `ide` capability may declare `[ide]` (`command` + `inject`, consumed by the
  `ide` verb). The authoritative schema reference is the module docstring of
  `sanity_gravity/plugins/manifest.py`.

## 2. Support tiers

An optional `tier` in `[plugin]` controls how far the agent travels:

| Tier | Local `build` / `up` | CI / publish | Notes |
| :--- | :------------------- | :----------- | :---- |
| `official` | yes | yes | Default when `tier` is undeclared |
| `community` | yes | no | Valid tag, never built by CI or published |
| `deprecated` | warns, proceeds | no | Still parses; lifecycle keeps working |

A tag's tier is the most restrictive tier among its three plugins.

**Start third-party or newly contributed agents at `tier = "community"`.**
Everything works locally, but the agent stays out of the CI build/verify and
release matrix (which costs 4 variants x 2 architectures per agent).
Maintainers promote an agent to `official` when demand signals justify the
CI and publishing cost; agents on the way out are marked `deprecated`.

## 3. The Dockerfile

`plugins/agents/oc/Dockerfile` (comments trimmed):

```dockerfile
# Default is unused; always overridden by --build-arg. Set to suppress Docker warning.
ARG BASE_IMAGE=ubuntu:24.04
FROM ${BASE_IMAGE}

ENV OPENCODE_DISABLE_AUTOUPDATE=true
RUN curl -fsSL https://opencode.ai/install | bash -s -- --no-modify-path && \
    test -f /root/.opencode/bin/opencode && \
    cp /root/.opencode/bin/opencode /usr/local/bin/opencode && \
    chmod 755 /usr/local/bin/opencode && \
    rm -rf /root/.opencode && \
    test -x /usr/local/bin/opencode
```

Conventions (all of `cc`, `cx`, and `oc` follow them):

- **`BASE_IMAGE` chain** — every agent layer starts with the `ARG
  BASE_IMAGE` + `FROM ${BASE_IMAGE}` pair; the CLI injects the desktop layer
  underneath at build time. The build context is the plugin's own directory.
- **Install for the sandbox user, not root** — upstream installers target
  `/root` (mode 700), unreadable for the non-root sandbox user created at
  runtime. Put the binary on `/usr/local/bin` (copy it out, or redirect
  `HOME` to a world-readable tree like `cx` does) and clean up the staging
  directory.
- **Never execute the agent binary at build time** — images are cross-built
  for amd64 + arm64 under qemu, where freshly installed binaries (especially
  Bun/Node-based ones) can hang or crash. Verify with `test -x`; leave
  `--version` checks to the integration tests, which run the real container.
- **Disable self-update** — the binary lives in root-owned `/usr/local/bin`,
  so in-place updates can never succeed for the sandbox user. Pin the image
  immutable via the vendor's switch (env var or config), e.g.
  `OPENCODE_DISABLE_AUTOUPDATE=true` above.
- The base layer already ships `curl`, `tar`, `ca-certificates`, and `git`;
  only install extra runtimes (like Node.js) when the agent truly needs them.

## 4. Verify locally

```bash
./sanity-cli plugins list             # manifest parsed and registered?
./sanity-cli list                     # new tags appear (non-official marked)
./sanity-cli build oc-none-ssh --dry-run   # inspect the planned layer chain
./sanity-cli build oc-none-ssh             # real build of the smallest variant
./sanity-cli up -v oc-none-ssh --password mysecret
ssh -p 2222 $USER@localhost                # then run the agent CLI inside
```

Run the test suite before submitting:

```bash
python3 -m pytest tests/ -x -q
```

## 5. Tests

Community-tier agents need no test changes — discovery and tag solving are
covered generically. If you aim for the official tier, mirror the per-agent
pattern:

- `tests/unit/test_oc_agent.py` — registry discovery, capability solving,
  and tier expectations; no Docker required.
- `tests/integration/test_oc_agent.py` — boots the real image and asserts
  the binary is installed and runnable *by the non-root user*. The module
  auto-skips when the image has not been built locally, so the suite stays
  green on machines that never built your agent.
