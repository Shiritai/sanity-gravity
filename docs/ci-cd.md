# CI/CD

Sanity-Gravity uses a **dual-path CI architecture** to keep PRs clean and releases reliable.

## Design Principles

- **PR = zero pollution**: PR builds never push images to the registry.
- **Release = full parallel**: release builds push, test, scan, and publish independently per architecture.
- **Reusable workflows**: shared building blocks (`_build.yml`, `_test.yml`, `_check.yml`, `_publish.yml`) are composed by the two entry-point workflows.

## Workflow Structure

```
.github/workflows/
├── ci-pr.yml               ← PR entry point (no registry push)
├── ci-release.yml          ← Release entry point (push + publish)
├── _build-and-verify.yml   ← Reusable: build + test + scan on same runner
├── _build.yml              ← Reusable: build + push to GHCR
├── _check.yml              ← Reusable: Trivy security scan
├── _test.yml               ← Reusable: pull from GHCR + pytest
└── _publish.yml            ← Reusable: multi-arch manifest assembly
```

## PR Pipeline (`ci-pr.yml`)

Triggers on pull requests to `main`, `feat/*`, `fix/*` (ignoring docs-only changes).

```
setup (discover valid tags via ./sanity-cli list --json)
  ├── verify-x64   (_build-and-verify.yml, amd64)
  └── verify-arm64  (_build-and-verify.yml, arm64)
```

Each `_build-and-verify.yml` run:
1. Builds all images locally on a single runner
2. Runs `pytest` integration tests
3. Runs Trivy security scans on all images

**No images are pushed.** The single-runner approach avoids needing to push intermediate images across jobs.

## Release Pipeline (`ci-release.yml`)

Triggers on push to `main`, version tags (`v*`), or published GitHub releases.

```
setup (discover tags + generate SHA-based transient tag)
  ├── build-x64    (_build.yml: build all, push to ghcr.io)
  ├── build-arm64   (_build.yml)
  ├── check-x64    (_check.yml: Trivy scan per image, needs build)
  ├── check-arm64
  ├── test-x64     (_test.yml: pull from GHCR, run pytest, needs build)
  ├── test-arm64
  └── publish      (_publish.yml: only on release/v* tag, needs all)
```

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
| `latest` | Multi-arch manifest, published on release |
| `v{version}` | Multi-arch manifest, published on version tag release |

## Tag Discovery

CI uses `./sanity-cli list --json` to dynamically discover valid tags, ensuring the pipeline always reflects the current dimension matrix without hardcoded values.
