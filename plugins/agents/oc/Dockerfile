# Default is unused; always overridden by --build-arg. Set to suppress Docker warning.
ARG BASE_IMAGE=ubuntu:24.04
FROM ${BASE_IMAGE}

# OpenCode Agent Layer
# Installs OpenCode (anomalyco/opencode) via the official installer. OpenCode
# ships as a single self-contained Bun-compiled binary, so no Node.js runtime
# is pulled in. The installer auto-detects x86_64/aarch64 (falling back to the
# AVX2-free "baseline" x64 build when needed), keeping the layer multi-arch;
# base already provides curl, tar, and ca-certificates.
#
# The install script hardcodes $HOME/.opencode/bin as its target (the
# OPENCODE_INSTALL_DIR override advertised upstream is no longer honored), so
# the binary is copied onto the global PATH and the root-only staging dir
# removed; `test -f` fails the build loudly if upstream moves the target
# again. --no-modify-path skips shell rc edits the copy makes pointless.
# `test -x` is the only build-time verification on purpose: running the Bun
# binary (e.g. `opencode --version`) is unreliable under qemu cross-builds.
#
# Auto-update is disabled image-wide: the binary lives in root-owned
# /usr/local/bin, so self-update could never succeed for the sandbox user and
# would only add startup noise. The ENV below only reaches supervisord
# children (the GUI path); SSH logins get a fresh PAM environment, so the
# entrypoint hook in rootfs/ additionally seeds the documented config-file
# switch (~/.config/opencode/opencode.json with "autoupdate": false) into the
# home of the user created at boot. Auth still lands in the user's own
# ~/.local/share/opencode.
ENV OPENCODE_DISABLE_AUTOUPDATE=true
RUN curl -fsSL https://opencode.ai/install | bash -s -- --no-modify-path && \
    test -f /root/.opencode/bin/opencode && \
    cp /root/.opencode/bin/opencode /usr/local/bin/opencode && \
    chmod 755 /usr/local/bin/opencode && \
    rm -rf /root/.opencode && \
    test -x /usr/local/bin/opencode

COPY rootfs/ /
