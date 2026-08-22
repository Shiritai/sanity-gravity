# Contributing to Sanity-Gravity

Thanks for your interest. Sanity-Gravity is a manifest-driven sandbox builder:
almost everything a contributor wants to add - a new agent, a new desktop, a new
connector - is **data plus a Dockerfile**, with no Python changes. The sections
below cover the development loop, the plugin path, and the (rarer, heavier) path
for adding a whole new tag dimension.

## Development setup

**Requirements**: Docker (with Compose v2), Python >= 3.11, and `git`.
Python 3.11 is a hard floor - the manifest loader uses the stdlib `tomllib`.

```bash
git clone https://github.com/shiritai/sanity-gravity.git
cd sanity-gravity
python -m venv .venv && source .venv/bin/activate
pip install -e ".[test]"   # the package + pytest, hypothesis, requests, urllib3
```

Install through the `test` extra rather than hand-picking packages: CI installs
the exact same way (`pip install -e ".[test]"`), so a dependency added to
`pyproject.toml` reaches CI without editing YAML - a contract test
(`tests/unit/test_packaging_contract.py`) enforces that there is no second,
hand-copied dependency list.

Repository layout:

| Path | What lives there |
|:-----|:-----------------|
| `plugins/<kind>/<slug>/` | Every agent, desktop, and connector: `manifest.toml` + `Dockerfile` (+ optional `hooks.py`, `rootfs/`) |
| `sandbox/` | The base image (`Dockerfile.base`) and the shared `rootfs/` overlay copied into every image |
| `sanity_gravity/` | The CLI package - `domain/` (value objects: tags, naming, plans), `plugins/` (manifest + registry), `hooks/` (per-verb phase logic), `verbs/`, `cli/` |
| `sanity-cli` | Entry point wrapper around `sanity_gravity.cli.main` |
| `config/` | Generated compose files, one per tag (gitignored - never hand-edit) |
| `tests/unit/`, `tests/integration/` | See "Running tests" |
| `docs/` | Architecture, tag system, CLI reference, CI/CD, Bring Your Own Agent |

## Running tests

Two layers, with different prerequisites:

```bash
python -m pytest tests/unit          # fast, hermetic, no Docker required
python -m pytest tests/integration   # boots real containers; needs built images
./sanity-cli test                    # the whole suite, the way CI runs it
```

**Unit tests** must stay hermetic: no Docker, no network, no writes outside
`tmp_path`. A unit test that needs a plugin tree builds one under `tmp_path` and
loads it with `PluginRegistry.from_dir(...)` rather than reaching for the real
`plugins/` directory.

**Integration tests** run against locally built images. Every file under
`tests/integration/` declares its precondition with exactly one of three
markers (a meta-test enforces this - "forgot the guard" must be
distinguishable from "needs nothing"):

```python
@pytest.mark.requires_image("cx-none-ssh")   # needs a built image (implies docker)
@pytest.mark.requires_docker                 # needs the daemon only
@pytest.mark.no_image                        # needs neither, and says so
```

`requires_image` marker semantics:

- **Locally (default)**: if `sanity-gravity:cx-none-ssh` is not present, the
  test is **skipped** with an actionable reason -
  `run ./sanity-cli build cx-none-ssh`. You never have to build the whole
  matrix to work on one agent.
- **In CI (`SANITY_REQUIRE_IMAGES=1`)**: a missing **official-tier** image is a
  **failure**, not a skip. This is deliberate: a broken build step must not
  silently turn the integration suite green by skipping everything. Missing
  community/deprecated images stay skips even in CI - the build matrix never
  promised them, so their absence is truthful.

Build what you need first:

```bash
./sanity-cli build ag-xfce-kasm      # one tag
./sanity-cli build all               # the whole official matrix (slow);
                                     # also the default when no tag is given
```

> **Note.** The marker is the single place a test names an image. Do not
> hand-roll `docker image inspect` guards or module-level `pytest.mark.skipif`
> for this - `tests/unit/test_matrix_guards.py` enforces the convention, and
> the coverage ratchet reads the markers.

## Adding an agent, desktop, or connector

This is the common case and it needs **no Python**: a directory, a
`manifest.toml`, and a `Dockerfile`. The full walkthrough - manifest fields,
capabilities, ports, tiers, announce templates - is in
[Bring Your Own Agent](docs/bring-your-own-agent.md); the authoritative schema
reference is the module docstring of `sanity_gravity/plugins/manifest.py`.

Checklist for the common case:

1. `mkdir -p plugins/<kind>/<slug>/` (`<kind>` is `agents`, `desktops`, or
   `connectors`; `<slug>` must match `^[a-z][a-z0-9]*$` - `-` and `_` are
   taken by the tag and layer-name grammars, and `base` is reserved).
2. Write `manifest.toml` (`[plugin]`, `[capabilities]`, `[build]`, plus any of
   the optional `[ports.*]` / `[compose]` / `[environment]` / `[announce]` /
   `[ide]` sections).
3. Write `Dockerfile`. It receives `--build-arg BASE_IMAGE=<parent layer>` from
   the planner; pin any upstream package by digest or version.
4. Start at `tier = "community"` (see "Support tiers").
5. Verify: `./sanity-cli build <your tag>` then `./sanity-cli up -v <your tag>`.
6. Add an integration smoke test with `@pytest.mark.requires_image("<tag>")`.
7. Update `docs/tags.md` (the dimension tables) and the README tag table.

## Adding a dimension

Adding a whole new **dimension** to the tag grammar (as opposed to a new member
of an existing one) is a rare, deliberate change: it multiplies the matrix and
touches the naming grammar. Work through every item - each one exists because
skipping it has produced a real defect before.

1. **Value object first.** Add the dimension as a field on `Tag`
   (`sanity_gravity/domain/tags.py`). A tag is one identity; a string is one of
   its renderings. Never let the new dimension travel through the codebase as a
   bare string, and never add a `split("-")` to recover it - if you need the
   agent, you write `tag.agent`.
2. **Naming, not f-strings.** Every derived name - image, compose service,
   container, env var, volume, compose file, GHCR ref, layer - comes from the
   `Naming` object (`sanity_gravity/domain/naming.py`). If the new dimension
   changes how a name is rendered, change the one method that renders it. A
   hand-written f-string that embeds a tag fails
   `tests/unit/test_naming_guard.py`, and `layer`/`parse_layer` must stay
   mutually inverse (a Hypothesis round-trip property asserts exactly that).
3. **Compatibility is data.** Express any cross-dimension constraint as
   `provides` / `requires` capability strings in the manifests. The solver is a
   pure set operation over the union of a tag's plugins
   (`sanity_gravity/domain/capability.py`) - it never learns member names.
   If you find yourself adding an `if` to the kernel to express "X only works
   on Y", you are writing a capability by hand: name it, declare it, delete the
   `if`.
4. **Member differences go in the manifest.** Two plugins of the same kind that
   differ only by a pinned upstream ref must share one Dockerfile and differ by
   one manifest field (`[build].from`, digest-pinned, root kinds only - every
   non-root layer gets its parent from the build plan). Two near-identical
   Dockerfiles is the symptom of a missing manifest field - add the field
   instead.
5. **Defaults live in data.** If the dimension is elidable from the tag string,
   its default member declares `[plugin].default = true`; the registry enforces
   at most one default per kind, official tier only, and only on elidable
   kinds. No default slug is ever hardcoded in `sanity_gravity/domain/` - the
   domain layer must not name a file in `plugins/`.
6. **Budget the matrix.** A new dimension multiplies `OFFICIAL_TAGS`. Ship the
   new members at `tier = "community"` first; see "Matrix budget" before
   promoting anything.
7. **Smoke test the new axis.** At least one integration test per new dimension
   member, via `@pytest.mark.requires_image(...)`. Official-tier tags without
   an integration reference fail `tests/unit/test_matrix_guards.py`.
8. **Document it.** `docs/tags.md` (grammar + dimension table),
   `docs/cli-reference.md` (any new flag), `docs/architecture.md` (if the build
   graph changed), and the README tag table.

## Support tiers

Every manifest may carry a `tier` in `[plugin]` (default: `official`). A tag's
tier is the **most restrictive** tier among its plugins - one community
component makes the whole tag community, because a final image embeds all of
its layers.

| Tier | Local `build` / `up` | CI build + verify | Published to GHCR | `pull` |
|:-----|:---------------------|:------------------|:------------------|:-------|
| `official` | Yes | Yes | Yes | Yes |
| `community` | Yes | No | No | No - build locally |
| `deprecated` | Yes, with a warning | No | No | No |

**New plugins start at `community`.** Promotion to `official` is a separate,
reviewable change that must come with: an integration smoke test, a passing
local `build` + `up`, and matrix-budget headroom (below).

## Matrix budget

The CI and publish surface is sized against the official matrix: `build all`
runs it serially per architecture under a workflow timeout, and every official
tag adds publish, scan, and pull fan-out across two architectures. That sizing
is implicit in `.github/`, and a manifest edit that widens the matrix does not
touch `.github/` at all - so the budget is enforced as a test instead:

```python
# tests/unit/test_matrix_guards.py
MAX_OFFICIAL_TAGS = 19
```

If your change makes `len(OFFICIAL_TAGS)` exceed the ceiling, the test fails.
Do **not** bump the number as a formality. The process is:

1. Keep the new plugin at `tier = "community"` and land it. This is almost
   always the right answer, and it unblocks users immediately.
2. If official-tier is genuinely warranted, re-derive the budget in the same PR:
   check the most recent release run's build/publish durations against the
   workflow `timeout-minutes`, account for the added GHCR packages and Trivy
   scans, and state the arithmetic in the PR description.
3. Raise `MAX_OFFICIAL_TAGS` in that same change, and update the comment above
   it with the new reasoning.

Two related guards live in the same file and follow the same "may only shrink"
discipline: `KNOWN_UNTESTED_OFFICIAL_TAGS` (official tags without an integration
reference - add a test, then delete the entry; never add one) and a lint that
forbids prefix-matching tag lists (`t.startswith("ag-")` goes silently blind the
moment another dimension prefixes the tag - filter via `resolve_tag(t).<dim>` instead).

## Code style

- **Python**: PEP 8, 4-space indent, `from __future__ import annotations`,
  type hints on public functions. Modules carry a docstring explaining *why*
  the module exists, not a restatement of its name. `ruff check .` must pass
  (the config lives in `pyproject.toml`; CI runs it on every PR).
- **Errors**: raise; do not `sys.exit` outside `sanity_gravity/cli/`. Library
  code that fails must raise an exception carrying an actionable hint; the CLI
  entry point is the only place that renders an error and picks an exit code.
  An empty return value means "this domain object does not exist", never
  "something went wrong".
- **Shell**: `#!/bin/bash` or `#!/bin/sh`, POSIX-compatible where practical,
  `set -euo pipefail` in non-trivial scripts.
- **Dockerfiles**: pin upstream images by digest and packages by version.
  Prefer a pinned tarball or distro package over `curl | sh` installers, and
  never execute the agent binary at build time (images cross-build under
  qemu) - see [Bring Your Own Agent](docs/bring-your-own-agent.md) for the
  full conventions.
- **Secrets**: plugins never declare `[environment]` entries that forward host
  API keys into the sandbox. Authentication happens in-container.

## Submitting a pull request

**Issue first.** For anything beyond a trivial fix (a typo, an obvious
one-line bug), open an issue before writing code and agree on the direction
there. A PR that arrives unannounced can be well-built and still roadmap-wrong;
the issue is where that mismatch is cheap to resolve.

**One PR, one base: `main`.** Every PR is based on `main` and must be able to
merge on its own. Do not stack a PR on another unmerged PR's branch: a stacked
PR cannot be reviewed in isolation, needs retargeting every time its base
moves, and blocks on everything below it. When a change is too large for one
PR, split it into consecutive PRs that each target `main` - land the first,
rebase, open the next. Maintainer-run refactor series follow the same rule:
they are published one PR at a time against `main`, each independently green,
never as an open chain.

1. Branch from `main`.
2. Keep the change focused: one concern per PR. Mechanical refactors and
   behavior changes go in separate commits (ideally separate PRs).
3. Run `python -m pytest tests/unit` locally; run the integration tests for the
   tags you touched.
4. Write a commit message that states the *why*. The subject line follows
   `type(scope): imperative summary` (e.g. `fix(manifest): reject plugin slugs
   outside ^[a-z][a-z0-9]*$`).
5. In the PR description: what changed, why, how you verified it, and - if you
   touched the matrix, the tag grammar, or CI - what the budget impact is.
6. Include screenshots for changes to the desktop or IDE experience.

By contributing you agree that your contributions are licensed under the
repository's Apache-2.0 license.
