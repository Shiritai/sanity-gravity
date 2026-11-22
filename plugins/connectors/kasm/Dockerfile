# Default is unused; always overridden by --build-arg. Set to suppress Docker warning.
ARG BASE_IMAGE=ubuntu:24.04
FROM ${BASE_IMAGE}

# Upstream's debs are not interchangeable across distro codenames; a pair
# with no pinned sum must stop the build rather than install the wrong one.
ENV KASM_VERSION=1.5.2
RUN arch=$(dpkg --print-architecture); \
    os=$(. /etc/os-release && echo "${ID}:${VERSION_CODENAME}"); \
    case "${os}/${arch}" in \
        ubuntu:noble/amd64)    sha256=89a5d1fbe9e032b122202be158a2b25f15c97e0a5b8dcf92a5e6835c7b7b2acd ;; \
        ubuntu:noble/arm64)    sha256=4d680f3d1eb77fb155ae67af7f9fa25d7fbd38a7f69ae146784c7f738e2eed1a ;; \
        debian:bookworm/amd64) sha256=5f4bfda43e89178782eac37ae463b1d95d16ac5e45da8b7989ec75404e764993 ;; \
        debian:bookworm/arm64) sha256=b847429cbcf95736fdd5c3be682eea38cae4d689f012eec9c2d5f221b175d1c2 ;; \
        *) echo "no pinned KasmVNC deb for '${os}/${arch}'" >&2; exit 1 ;; \
    esac; \
    deb="kasmvncserver_${os%%:*}_${os#*:}_${KASM_VERSION}_${arch}.deb" && \
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
