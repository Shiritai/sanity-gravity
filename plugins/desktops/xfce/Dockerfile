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
    # gvfs: backs Thunar's Places "Computer" entry (computer:///) over
    # D-Bus; without it GIO has no backend for the scheme. Base package
    # only, not gvfs-backends/gvfs-fuse (smb/nfs/mtp/... this container
    # never uses) -- udisks2 comes along as gvfs's own hard dependency.
    gvfs \
    x11-utils \
    x11-xserver-utils \
    x11-apps \
    xdotool \
    mesa-utils \
    fonts-noto-cjk \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
