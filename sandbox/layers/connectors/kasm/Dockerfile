# Default is unused; always overridden by --build-arg. Set to suppress Docker warning.
ARG BASE_IMAGE=ubuntu:24.04
FROM ${BASE_IMAGE}

# Install KasmVNC
# Using a fixed version for stability with SHA256 integrity verification
ENV KASM_VERSION=1.4.0
RUN arch=$(dpkg --print-architecture); \
    KASM_DEB="kasmvncserver_noble_${KASM_VERSION}_${arch}.deb" && \
    curl -L -O "https://github.com/kasmtech/KasmVNC/releases/download/v${KASM_VERSION}/${KASM_DEB}" && \
    if [ "$arch" = "amd64" ]; then \
        echo "12bac6014149c5fdee75f0d403785aaa3e5dd4ea222de73253a5d4181bc9567e  ${KASM_DEB}" | sha256sum -c -; \
    else \
        echo "120d9462cb5e917cad91a23f6cb0b780c06f701def40e900b29f996979200638  ${KASM_DEB}" | sha256sum -c -; \
    fi && \
    apt-get update && apt-get install -y "./${KASM_DEB}" ssl-cert && \
    rm "${KASM_DEB}" && \
    rm -f /etc/ssl/private/ssl-cert-snakeoil.key /etc/ssl/certs/ssl-cert-snakeoil.pem && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Add Supervisor Config for Kasm
COPY layers/connectors/kasm/supervisord.conf /etc/supervisor/conf.d/kasm.conf

# Add Kasm Startup Script
COPY layers/connectors/kasm/startup.sh /usr/local/bin/kasm-startup.sh
RUN chmod +x /usr/local/bin/kasm-startup.sh

# Expose Port 8444
EXPOSE 8444
