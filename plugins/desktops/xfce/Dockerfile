ARG BASE_IMAGE=sanity-gravity:_base
FROM ${BASE_IMAGE}

# Install XFCE4 and Desktop Utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    xfce4 \
    xfce4-terminal \
    xfce4-taskmanager \
    xfce4-screenshooter \
    xfce4-notifyd \
    xfce4-clipman-plugin \
    xfce4-whiskermenu-plugin \
    thunar-archive-plugin \
    dbus \
    dbus-x11 \
    x11-utils \
    x11-xserver-utils \
    x11-apps \
    xdotool \
    mesa-utils \
    fonts-noto-cjk \
    && apt-get autoremove -y && \
    rm -rf /usr/share/doc/* /usr/share/info/* /usr/share/lintian/* /usr/share/man/* \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Register standard desktop session launcher contract
RUN echo '#!/bin/sh\nexec startxfce4' > /usr/local/bin/desktop-session \
    && chmod +x /usr/local/bin/desktop-session

