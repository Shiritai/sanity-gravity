FROM sanity-gravity:core

# Install TigerVNC and noVNC
RUN apt-get update && apt-get install -y --no-install-recommends \
    tigervnc-standalone-server \
    tigervnc-common \
    tigervnc-tools \
    novnc \
    websockify \
    python3-numpy \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Fix noVNC index (redirect to vnc.html)
RUN ln -s /usr/share/novnc/vnc.html /usr/share/novnc/index.html

# Add Supervisor Config for VNC
COPY variants/vnc/supervisord.conf /etc/supervisor/conf.d/vnc.conf

# Add VNC Startup Script
COPY variants/vnc/startup.sh /usr/local/bin/vnc-startup.sh
RUN chmod +x /usr/local/bin/vnc-startup.sh

# Expose Ports
# 5901: VNC
# 6901: noVNC (HTTP)
EXPOSE 5901 6901
