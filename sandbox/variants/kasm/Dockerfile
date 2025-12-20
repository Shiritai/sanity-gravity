FROM sanity-gravity:core

# Install KasmVNC
# Using a fixed version for stability
ENV KASM_VERSION=1.3.2
ENV KASM_DEB=kasmvncserver_jammy_${KASM_VERSION}_amd64.deb

RUN curl -L -O https://github.com/kasmtech/KasmVNC/releases/download/v${KASM_VERSION}/${KASM_DEB} && \
    apt-get update && apt-get install -y ./$KASM_DEB ssl-cert && \
    rm $KASM_DEB && \
    apt-get clean && rm -rf /var/lib/apt/lists/* && \
    make-ssl-cert generate-default-snakeoil --force-overwrite

# Add Supervisor Config for Kasm
COPY variants/kasm/supervisord.conf /etc/supervisor/conf.d/kasm.conf

# Add Kasm Startup Script
COPY variants/kasm/startup.sh /usr/local/bin/kasm-startup.sh
RUN chmod +x /usr/local/bin/kasm-startup.sh

# Expose Port 8444
EXPOSE 8444
