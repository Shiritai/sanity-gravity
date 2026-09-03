# Default is unused; always overridden by --build-arg. Set to suppress Docker warning.
ARG BASE_IMAGE=ubuntu:24.04
FROM ${BASE_IMAGE}

# Install KasmVNC
# Using a fixed version for stability with SHA256 integrity verification.
# KasmVNC ships distro-specific .debs: noble (Ubuntu 24.04) and bookworm
# (Debian 12) have different shared-library requirements, so the layer
# picks the matching package from /etc/os-release at build time (the
# same connector layer builds on both base images).
ENV KASM_VERSION=1.5.0
RUN arch=$(dpkg --print-architecture); \
    if grep -q "ID=debian" /etc/os-release; then KASM_DIST="bookworm"; else KASM_DIST="noble"; fi; \
    KASM_DEB="kasmvncserver_${KASM_DIST}_${KASM_VERSION}_${arch}.deb" && \
    curl -L -O "https://github.com/kasmtech/KasmVNC/releases/download/v${KASM_VERSION}/${KASM_DEB}" && \
    case "${KASM_DIST}_${arch}" in \
        noble_amd64)    echo "f599fe02e2175b9817b6165f74a5d2bebdc73118dde9181ba3410963bed7ae1e  ${KASM_DEB}" | sha256sum -c - ;; \
        noble_arm64)    echo "c9199cf4753208bfb69fd016a9780242bebfc43370cc38c97d61e90a3c783e04  ${KASM_DEB}" | sha256sum -c - ;; \
        bookworm_amd64) echo "770fd3df51510beecc89666879d82faf411276e68c6e11df612f736b891b5f71  ${KASM_DEB}" | sha256sum -c - ;; \
        bookworm_arm64) echo "aa83a1a6c9069d1a02239988b07a3a2a082a433042b4d4ee2b9e9f6b2df9643c  ${KASM_DEB}" | sha256sum -c - ;; \
        *) echo "unsupported: ${KASM_DIST}_${arch}" >&2; exit 1 ;; \
    esac && \
    apt-get update && apt-get install -y "./${KASM_DEB}" ssl-cert openssl && \
    rm "${KASM_DEB}" && \
    apt-get autoremove -y && \
    rm -rf /usr/share/doc/* /usr/share/info/* /usr/share/lintian/* /usr/share/man/* \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Add Supervisor Config for Kasm
COPY supervisord.conf /etc/supervisor/conf.d/kasm.conf

# Inject entrypoint hooks
COPY rootfs/ /

# Bake a stable localhost CA + server certificate (see
# /usr/local/bin/gen-localhost-certs.sh). The snakeoil package default is
# anonymous and triggers both a hostname and a trust warning; our cert is
# valid for localhost/127.0.0.1 and ships a CA that can be imported once into
# the browser/OS trust store. Baked at build time (not regenerated per
# container) so one CA import survives container re-creations.
RUN /usr/local/bin/gen-localhost-certs.sh

# Add Kasm Startup Script
COPY startup.sh /usr/local/bin/kasm-startup.sh
RUN chmod +x /usr/local/bin/kasm-startup.sh

# Expose Port 8444
EXPOSE 8444
