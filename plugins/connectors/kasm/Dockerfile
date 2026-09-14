# Default is unused; always overridden by --build-arg. Set to suppress Docker warning.
ARG BASE_IMAGE=ubuntu:24.04
FROM ${BASE_IMAGE}

# Upstream's debs are not interchangeable across distro codenames; a pair
# with no pinned sum must stop the build rather than install the wrong one.
ENV KASM_VERSION=1.5.0
RUN arch=$(dpkg --print-architecture); \
    os=$(. /etc/os-release && echo "${ID}:${VERSION_CODENAME}"); \
    case "${os}/${arch}" in \
        ubuntu:noble/amd64)    sha256=f599fe02e2175b9817b6165f74a5d2bebdc73118dde9181ba3410963bed7ae1e ;; \
        ubuntu:noble/arm64)    sha256=c9199cf4753208bfb69fd016a9780242bebfc43370cc38c97d61e90a3c783e04 ;; \
        debian:bookworm/amd64) sha256=770fd3df51510beecc89666879d82faf411276e68c6e11df612f736b891b5f71 ;; \
        debian:bookworm/arm64) sha256=aa83a1a6c9069d1a02239988b07a3a2a082a433042b4d4ee2b9e9f6b2df9643c ;; \
        *) echo "no pinned KasmVNC deb for '${os}/${arch}'" >&2; exit 1 ;; \
    esac; \
    deb="kasmvncserver_${os#*:}_${KASM_VERSION}_${arch}.deb" && \
    curl -L -O "https://github.com/kasmtech/KasmVNC/releases/download/v${KASM_VERSION}/${deb}" && \
    echo "${sha256}  ${deb}" | sha256sum -c - && \
    apt-get update && apt-get install -y "./${deb}" ssl-cert && \
    rm "${deb}" && \
    rm -f /etc/ssl/private/ssl-cert-snakeoil.key /etc/ssl/certs/ssl-cert-snakeoil.pem && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Add Supervisor Config for Kasm
COPY supervisord.conf /etc/supervisor/conf.d/kasm.conf

# Inject entrypoint hooks
COPY rootfs/ /

# Add Kasm Startup Script
COPY startup.sh /usr/local/bin/kasm-startup.sh
RUN chmod +x /usr/local/bin/kasm-startup.sh

# Expose Port 8444
EXPOSE 8444
