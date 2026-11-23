# CI/CD

Sanity-Gravity uses a **dual-path CI architecture** to keep PRs clean and releases reliable.

## Design Principles

- **PR = zero pollution**: PR builds never push images to the registry.
- **Release = full parallel**: release builds push, test, scan, and publish independently per architecture.
- **Reusable workflows**: shared building blocks (`_build-and-verify.yml`, `_build.yml`, `_test.yml`, `_check.yml`, `_publish.yml`) are composed by the entry-point workflows.

## Workflow Structure

```
.github/workflows/
├── hermetic.yml            ← Every PR + every push to main: lint + hermetic tests
├── ci-pr.yml               ← PR entry point (no registry push)
├── ci-release.yml          ← Release entry point (push + publish)
├── scheduled-build.yml     ← 1st and 15th: rebuild + test + scan, no push
├── _build-and-verify.yml   ← Reusable: build + test + scan on same runner
├── _build.yml              ← Reusable: build + push to GHCR
├── _check.yml              ← Reusable: Trivy security scan
├── _test.yml               ← Reusable: pull from GHCR + pytest
└── _publish.yml            ← Reusable: multi-arch manifest assembly
```

## Required Checks

Branch protection on `main` requires three checks: `hermetic`, `verify-x64 / build-and-verify`, and `verify-arm64 / build-and-verify`. GitHub names a check after its job (`<caller job> / <called job>` for a reusable workflow), so renaming these jobs means changing the branch protection setting too; `tests/unit/test_ci_checks.py` pins the names.

No workflow that produces a required check filters its trigger by path: a workflow skipped that way reports nothing and leaves the check Pending, while a job skipped by `if:` reports Success.

## Hermetic (`hermetic.yml`)

Triggers on every pull request and every push to `main`, docs-only ones included (the tests read `docs/`, `CONTRIBUTING.md`, and the READMEs).

The `hermetic` job runs `ruff check .`, `lint-imports`, and `pytest -m "not requires_docker"` with `HOME` pointed at an empty temp directory, then fails if the tests left anything in that `HOME` or in the checkout beyond the tool caches, `__pycache__/`, and `sanity_gravity.egg-info/`.

## PR Pipeline (`ci-pr.yml`)

Triggers on pull requests to `main`, `feat/*`, `fix/*`.

```
setup (discover valid tags via ./sanity-cli list --json;
       decide needs_images from the PR's changed paths)
  ├── verify-x64   (_build-and-verify.yml, amd64)
  └── verify-arm64  (_build-and-verify.yml, arm64)
```

`needs_images` is false only when every changed path is docs-only (`sanity_gravity/core/changes.py`); then `build-and-verify` is skipped and both verify checks report as skipped, which counts as passing.

Each `_build-and-verify.yml` run:
1. Builds all images locally on a single runner
2. Runs `pytest` integration tests (`SANITY_DISPOSABLE_HOST=1`: the runner is a fresh VM, so host-changing tests run)
3. Runs Trivy security scans on all images

**No images are pushed.** The single-runner approach avoids needing to push intermediate images across jobs.

## Release Pipeline (`ci-release.yml`)

Triggers on push to `main` (ignoring docs-only changes) and on version tags (`v*`). Publishing a GitHub release creates its tag, and that tag push is what runs the pipeline; there is no separate `release` trigger, so a version is built and published once.

```
setup (discover tags + generate SHA-based transient tag)
  ├── build-x64    (_build.yml: build all, push to ghcr.io)
  ├── build-arm64   (_build.yml)
  ├── check-x64    (_check.yml: Trivy scan per image, needs build)
  ├── check-arm64
  ├── test-x64     (_test.yml: pull from GHCR, run pytest, needs build)
  ├── test-arm64
  └── publish      (_publish.yml: only on a v* tag, needs all)
```

## Scheduled Build (`scheduled-build.yml`)

Runs at 03:00 UTC on the 1st and 15th of each month (cron cannot express every 14 days), and on demand via `workflow_dispatch`.

```
setup (discover valid tags via ./sanity-cli list --json)
  ├── verify-x64   (_build-and-verify.yml, amd64)
  └── verify-arm64  (_build-and-verify.yml, arm64)
```

The same build, tests, and Trivy gate as a PR, on the official-tier tags, built without cache on fresh runners. The base digests stay pinned, but the root layer's `apt-get upgrade` pulls the current distro fixes, so a newly fixable HIGH/CRITICAL turns this run red even when nobody has pushed. **Nothing is pushed or published**; acting on a red run means bumping what it names and cutting a release. Trivy does not match software installed outside the distro archives (Chrome from Google's repo, the KasmVNC deb) against distro advisories, so those versions are tracked by hand.

## Registry

Images are published to **GitHub Container Registry (GHCR)**.

### Naming Pattern

Each final tag gets its own GHCR package:

```
ghcr.io/{owner}/{repo}-{tag}:{version}-{arch}
```

For example:
- `ghcr.io/shiritai/sanity-gravity-ag-xfce-kasm:sha-abc1234-amd64`
- `ghcr.io/shiritai/sanity-gravity-cc-none-ssh:latest`

### Published Tags

| Tag | When |
|:----|:-----|
| `sha-{short_sha}-{arch}` | Every release build (transient, per-arch) |
| `latest` | Multi-arch manifest, published on a version tag without `-` (not on pre-releases such as `v0.4.0-rc.1`) |
| `v{version}` | Multi-arch manifest, published on every version tag |

## Tag Discovery

CI uses `./sanity-cli list --json` to dynamically discover valid tags, ensuring the pipeline always reflects the current dimension matrix without hardcoded values.
