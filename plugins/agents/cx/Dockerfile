# Default is unused; always overridden by --build-arg. Set to suppress Docker warning.
ARG BASE_IMAGE=ubuntu:24.04
FROM ${BASE_IMAGE}

# Codex CLI Agent Layer
# Installs the OpenAI Codex CLI from the pinned npm platform tarball instead
# of the official installer: the installer resolves versions and asset
# digests through unauthenticated api.github.com calls, which hit shared
# rate limits on CI runners and fail intermittently. The npm registry
# tarball URL is built for anonymous bulk downloads and pins an exact
# version, so the layer builds deterministically. Codex ships as a
# statically-linked musl binary (Rust), so no Node.js runtime is pulled in.
#
# The package tree lands in a world-readable /opt/codex (the binary resolves
# bundled helpers like rg relative to its own path) with a symlink onto the
# global PATH, mirroring the official installer's layout. Runtime config and
# auth still land in the user's own ~/.codex.
ARG CODEX_VERSION=0.143.0
RUN arch="$(dpkg --print-architecture)" && \
    case "$arch" in \
        amd64) target="x86_64-unknown-linux-musl"; slug="linux-x64" ;; \
        arm64) target="aarch64-unknown-linux-musl"; slug="linux-arm64" ;; \
        *) echo "unsupported architecture: $arch" >&2; exit 1 ;; \
    esac && \
    mkdir -p /opt/codex && \
    curl -fsSL "https://registry.npmjs.org/@openai/codex/-/codex-${CODEX_VERSION}-${slug}.tgz" \
        | tar -xz -C /opt/codex --strip-components=1 && \
    ln -s "/opt/codex/vendor/${target}/bin/codex" /usr/local/bin/codex && \
    chmod -R a+rX /opt/codex && \
    test -x /usr/local/bin/codex

COPY rootfs/ /
