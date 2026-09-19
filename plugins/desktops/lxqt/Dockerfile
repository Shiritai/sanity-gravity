ARG BASE_IMAGE=sanity-gravity:_base
FROM ${BASE_IMAGE}

# Install LXQt Desktop and Core Utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    # --- LXQt Core & Session ---
    # lxqt-core pulls in lxqt-session (startlxqt), lxqt-panel, pcmanfm-qt,
    # lxqt-runner, lxqt-qtplugin, lxqt-policykit, lxqt-notificationd,
    # lxqt-config, lxqt-globalkeys, lxqt-system-theme, qterminal, etc.
    # LXQt ships no window manager of its own (it is WM-agnostic); xfwm4
    # is the standard WM for LXQt on both Ubuntu and Debian, so lxqt-session
    # finds exactly one known WM at start and selects it without prompting.
    lxqt-core \
    xfwm4 \
    # --- Core Utilities ---
    featherpad \
    lximage-qt \
    qps \
    qlipper \
    lxqt-archiver \
    # --- Shared X11, DBus & System Utilities ---
    dbus \
    dbus-x11 \
    # gvfs: backs pcmanfm-qt's Places "Computer" entry (computer:///) over
    # D-Bus; base package only, not gvfs-backends/-fuse (smb/nfs/mtp/... this
    # container never uses).
    gvfs \
    x11-utils \
    x11-xserver-utils \
    x11-apps \
    xdotool \
    mesa-utils \
    fonts-noto-cjk \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# The session launcher the VNC-family connectors exec. No display manager
# runs under Xvnc, so nothing else sets the XDG session identity: without
# it pcmanfm-qt does not draw the desktop and the LXQt components do not
# recognize the session.
RUN printf '%s\n' \
    '#!/bin/sh' \
    'exec env XDG_CURRENT_DESKTOP=LXQt DESKTOP_SESSION=lxqt XDG_SESSION_DESKTOP=lxqt XDG_SESSION_TYPE=x11 startlxqt' \
    > /usr/local/bin/desktop-session \
    && chmod +x /usr/local/bin/desktop-session
